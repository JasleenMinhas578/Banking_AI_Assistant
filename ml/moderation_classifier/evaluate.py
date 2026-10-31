"""Scores the saved classifier on the red-team set, which is never used for training.

    uv run python evaluate.py

The red-team set is hand-written: new phrasings, slang, and safe messages that
look scary ("kill my card", "ignore that, what's my balance"). Its numbers are
the honest ones; validation on held-out templates is the optimistic one.
Writes reports/red_team.md.
"""

import csv
import json
from pathlib import Path

import joblib

from labels import HARMFUL, LABELS, SAFE
from pipeline import confusion_table, per_class_table, sweep, sweep_table

HERE = Path(__file__).parent
RED_TEAM = HERE / "data" / "red_team.csv"
MODEL_DIR = HERE / "model"
REPORTS = HERE / "reports"


def outcome(truth: str, predicted: str, confidence: float, threshold: float) -> str:
    if confidence < threshold:
        return "escalated"  # tier 3 decides; not a mistake by itself
    if predicted == truth:
        return "correct"
    if truth in HARMFUL and predicted == SAFE:
        return "MISSED"  # harmful passed as safe: the dangerous mistake
    if truth == SAFE:
        return "false block"
    return "wrong label"  # stopped for the wrong reason, or off-topic passed as safe


def evaluate(
    model_dir: Path = MODEL_DIR, red_team: Path = RED_TEAM, reports: Path = REPORTS
) -> dict[str, int]:
    pipeline = joblib.load(model_dir / "classifier.joblib")
    threshold = json.loads((model_dir / "metadata.json").read_text())["threshold"]
    with red_team.open(newline="") as file:
        rows = list(csv.DictReader(file))

    classes = list(pipeline.classes_)
    probabilities = pipeline.predict_proba([r["text"] for r in rows])
    labels = [r["label"] for r in rows]
    predicted = [classes[i] for i in probabilities.argmax(axis=1)]
    confidence = probabilities.max(axis=1)
    outcomes = [
        outcome(t, p, float(c), threshold)
        for t, p, c in zip(labels, predicted, confidence, strict=True)
    ]
    counts = {
        name: outcomes.count(name)
        for name in ["correct", "escalated", "wrong label", "false block", "MISSED"]
    }

    mistakes = ["| Message | True | Model said | Confidence | Outcome |", "|---|---|---|---|---|"]
    for row, p, c, o in zip(rows, predicted, confidence, outcomes, strict=True):
        if o != "correct":
            mistakes.append(f"| {row['text']} | {row['label']} | {p} | {c:.2f} | {o} |")

    reports.mkdir(parents=True, exist_ok=True)
    summary = " · ".join(f"{name}: {count}" for name, count in counts.items())
    (reports / "red_team.md").write_text(
        "\n\n".join(
            [
                "# Red-team report",
                f"{len(rows)} hand-written messages the model never trained on. "
                f"Threshold {threshold:.2f} (chosen on validation).",
                f"**{summary}**",
                "Escalated messages go to tier 3 (Llama Guard + checklist), so only "
                "MISSED and false blocks are real mistakes at this tier.",
                "## Threshold sweep on the red-team set",
                sweep_table(sweep(labels, probabilities, classes), threshold),
                "## Confusion matrix (top label, before the threshold)",
                confusion_table(labels, predicted, LABELS),
                "## Per label",
                per_class_table(labels, predicted, LABELS),
                "## Everything not decided correctly",
                "\n".join(mistakes),
            ]
        )
        + "\n"
    )
    return counts


def main() -> None:
    counts = evaluate()
    total = sum(counts.values())
    print(f"Red team ({total} messages): " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    print("Details in reports/red_team.md")


if __name__ == "__main__":
    main()
