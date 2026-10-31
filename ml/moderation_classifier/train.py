"""Trains the tier-2 moderation classifier and picks its threshold.

    uv run python train.py

1. Cross-validate by template (5 folds): every message is scored by a model
   that never saw its template, so the scores reflect unseen phrasings.
2. Sweep thresholds on those scores and pick the lowest one where under 2% of
   harmful messages pass as safe and under 5% of safe ones are blocked.
3. Train on everything and save model/classifier.joblib + model/metadata.json.
4. Write reports/validation.md: the sweep, the confusion matrix, per-label scores.
"""

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import sklearn
from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict

from labels import LABELS
from pipeline import (
    MAX_FALSE_BLOCKS,
    MAX_MISSED,
    as_dict,
    build_pipeline,
    choose_threshold,
    confusion_table,
    per_class_table,
    sweep,
    sweep_table,
)

HERE = Path(__file__).parent
DATA = HERE / "data" / "utterances.csv"
MODEL_DIR = HERE / "model"
REPORTS = HERE / "reports"
FOLDS = 5
SEED = 7


def load(path: Path) -> list[dict[str, str]]:
    with Path(path).open(newline="") as file:
        return list(csv.DictReader(file))


def train(
    rows: list[dict[str, str]],
    model_dir: Path = MODEL_DIR,
    reports: Path = REPORTS,
    folds: int = FOLDS,
) -> dict:
    texts = [r["text"] for r in rows]
    labels = [r["label"] for r in rows]
    templates = [r["template"] for r in rows]

    splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=SEED)
    probabilities = cross_val_predict(
        build_pipeline(), texts, labels, groups=templates, cv=splitter, method="predict_proba"
    )
    classes = sorted(set(labels))  # cross_val_predict orders columns like classes_
    swept = sweep(labels, probabilities, classes)
    threshold = choose_threshold(swept)
    chosen = next(row for row in swept if row.threshold == threshold)
    predicted = [classes[i] for i in probabilities.argmax(axis=1)]

    final = build_pipeline()
    final.fit(texts, labels)

    metadata = {
        "threshold": threshold,
        "labels": list(final.classes_),
        "sklearn_version": sklearn.__version__,
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "examples": len(rows),
        "templates": len(set(templates)),
        "validation": {
            "method": f"{folds}-fold cross-validation grouped by template",
            "at_threshold": as_dict([chosen])[0],
            "sweep": as_dict(swept),
        },
    }
    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, model_dir / "classifier.joblib")
    (model_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

    reports.mkdir(parents=True, exist_ok=True)
    (reports / "validation.md").write_text(
        "\n\n".join(
            [
                "# Validation report",
                f"{len(rows)} examples from {len(set(templates))} templates, scored with "
                f"{folds}-fold cross-validation grouped by template: each message was scored "
                "by a model that never saw its template.",
                f"Targets: missed harmful ≤ {MAX_MISSED:.0%}, false blocks ≤ "
                f"{MAX_FALSE_BLOCKS:.0%}. Chosen threshold: **{threshold:.2f}** "
                "(the lowest that meets both, so the fewest messages wait for tier 3).",
                "## Threshold sweep",
                sweep_table(swept, threshold),
                "## Confusion matrix (top label, before the threshold)",
                confusion_table(labels, predicted, LABELS),
                "## Per label",
                per_class_table(labels, predicted, LABELS),
            ]
        )
        + "\n"
    )
    return metadata


def main() -> None:
    metadata = train(load(DATA))
    at = metadata["validation"]["at_threshold"]
    print(f"Trained on {metadata['examples']} examples. Threshold {metadata['threshold']:.2f}:")
    print(
        f"  escalated {at['escalated']:.1%} · missed harmful {at['missed']:.1%} · "
        f"false blocks {at['false_blocks']:.1%}"
    )
    print("Saved model/classifier.joblib, model/metadata.json and reports/validation.md")


if __name__ == "__main__":
    main()
