"""The dataset builder, the threshold rule and a full train → evaluate round trip."""

import json
from pathlib import Path

import joblib
import numpy as np

import evaluate
import generate
import train
from labels import LABELS, SAFE
from pipeline import DEFAULT_THRESHOLD, SweepRow, choose_threshold, sweep


def test_dataset_is_deterministic_and_covers_every_label() -> None:
    first, second = generate.build(), generate.build()

    assert first == second
    assert {row["label"] for row in first} == set(LABELS)
    assert len({row["text"].lower() for row in first}) == len(first)  # no duplicates


def test_red_team_is_never_in_the_training_data() -> None:
    red_team = {row["text"].lower() for row in train.load(evaluate.RED_TEAM)}
    training = {row["text"].lower() for row in generate.build()}

    assert not red_team & training


def test_threshold_is_the_lowest_one_meeting_both_targets() -> None:
    rows = [
        SweepRow(0.5, 0.1, missed=0.08, false_blocks=0.01, decided_accuracy=0.9),
        SweepRow(0.6, 0.2, missed=0.01, false_blocks=0.09, decided_accuracy=0.9),
        SweepRow(0.7, 0.3, missed=0.01, false_blocks=0.02, decided_accuracy=0.9),
        SweepRow(0.8, 0.4, missed=0.0, false_blocks=0.0, decided_accuracy=1.0),
    ]

    assert choose_threshold(rows) == 0.7
    assert choose_threshold(rows[:2]) == DEFAULT_THRESHOLD


def test_sweep_counts_a_confident_safe_on_harmful_text_as_missed() -> None:
    classes = [SAFE, "abuse"]
    probabilities = np.array([[0.9, 0.1], [0.4, 0.6]])  # abuse called safe; safe called abuse

    row = sweep(["abuse", SAFE], probabilities, classes)[0]  # threshold 0.50

    assert (row.missed, row.false_blocks, row.escalated) == (1.0, 1.0, 0.0)


def test_train_and_evaluate_round_trip(tmp_path: Path) -> None:
    rows = generate.build()[:900]

    metadata = train.train(rows, model_dir=tmp_path / "model", reports=tmp_path, folds=3)
    counts = evaluate.evaluate(model_dir=tmp_path / "model", reports=tmp_path)

    saved = json.loads((tmp_path / "model" / "metadata.json").read_text())
    model = joblib.load(tmp_path / "model" / "classifier.joblib")
    assert saved["threshold"] == metadata["threshold"]
    assert sorted(saved["labels"]) == sorted(LABELS)
    assert model.predict(["what's my balance"])[0] == SAFE
    assert sum(counts.values()) == len(train.load(evaluate.RED_TEAM))
    assert (tmp_path / "validation.md").exists() and (tmp_path / "red_team.md").exists()
