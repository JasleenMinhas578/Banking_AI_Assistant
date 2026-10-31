"""The model, the threshold sweep and the metrics, shared by train.py and evaluate.py.

How the agent uses the model: if the top label's probability is at or above the
threshold, the classifier decides. Below it, the message goes to tier 3 (the
LLM judge). So two numbers matter at each threshold:

- missed: harmful messages the classifier confidently called safe (dangerous)
- false blocks: safe messages it confidently called unsafe (annoying)
Everything below the threshold is escalated, which costs time but not safety.
"""

from dataclasses import asdict, dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from labels import HARMFUL, SAFE

THRESHOLDS = [round(0.5 + 0.05 * step, 2) for step in range(10)]  # 0.50 ... 0.95
MAX_MISSED = 0.02  # a harmful message passing as safe is the costly mistake
MAX_FALSE_BLOCKS = 0.05  # under 5% of real requests confidently blocked
DEFAULT_THRESHOLD = 0.85  # the design doc's value, if no threshold meets both targets


def build_pipeline() -> Pipeline:
    """Word and character n-grams (character ones survive typos), then logistic regression."""
    features = FeatureUnion(
        [
            (
                "words",
                TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, strip_accents="unicode"),
            ),
            (
                "chars",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    sublinear_tf=True,
                    min_df=2,
                    strip_accents="unicode",
                ),
            ),
        ]
    )
    model = LogisticRegression(C=10.0, max_iter=3000, class_weight="balanced")
    return Pipeline([("features", features), ("model", model)])


@dataclass(frozen=True)
class SweepRow:
    threshold: float
    escalated: float  # share of messages sent on to tier 3
    missed: float  # share of harmful messages confidently called safe
    false_blocks: float  # share of safe messages confidently called unsafe
    decided_accuracy: float  # accuracy on the messages the classifier decided


def sweep(labels: list[str], probabilities: np.ndarray, classes: list[str]) -> list[SweepRow]:
    top = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    predicted = np.array(classes)[top]
    truth = np.array(labels)
    unsafe, safe = np.isin(truth, HARMFUL), truth == SAFE
    rows = []
    for threshold in THRESHOLDS:
        decided = confidence >= threshold
        missed = (decided & unsafe & (predicted == SAFE)).sum() / max(unsafe.sum(), 1)
        false_blocks = (decided & safe & (predicted != SAFE)).sum() / max(safe.sum(), 1)
        correct = (predicted[decided] == truth[decided]).mean() if decided.any() else 1.0
        rows.append(
            SweepRow(
                threshold,
                float(1 - decided.mean()),
                float(missed),
                float(false_blocks),
                float(correct),
            )
        )
    return rows


def choose_threshold(rows: list[SweepRow]) -> float:
    """The lowest threshold that meets both targets: fewest messages sent to the slow tier."""
    for row in rows:
        if row.missed <= MAX_MISSED and row.false_blocks <= MAX_FALSE_BLOCKS:
            return row.threshold
    return DEFAULT_THRESHOLD


def sweep_table(rows: list[SweepRow], chosen: float) -> str:
    lines = [
        "| Threshold | Escalated to tier 3 | Missed harmful | False blocks | Accuracy when "
        "deciding |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        mark = " ✅" if row.threshold == chosen else ""
        lines.append(
            f"| {row.threshold:.2f}{mark} | {row.escalated:.1%} | {row.missed:.1%} | "
            f"{row.false_blocks:.1%} | {row.decided_accuracy:.1%} |"
        )
    return "\n".join(lines)


def confusion_table(labels: list[str], predicted: list[str], classes: list[str]) -> str:
    """Rows are the true label, columns what the model said."""
    header = "| true ↓ / predicted → | " + " | ".join(classes) + " |"
    lines = [header, "|---" * (len(classes) + 1) + "|"]
    for true in classes:
        counts = [
            sum(1 for t, p in zip(labels, predicted, strict=True) if t == true and p == col)
            for col in classes
        ]
        lines.append(f"| **{true}** | " + " | ".join(str(c) for c in counts) + " |")
    return "\n".join(lines)


def per_class_table(labels: list[str], predicted: list[str], classes: list[str]) -> str:
    lines = ["| Label | Precision | Recall | Examples |", "|---|---|---|---|"]
    for label in classes:
        tp = sum(1 for t, p in zip(labels, predicted, strict=True) if t == p == label)
        said = sum(1 for p in predicted if p == label)
        actual = sum(1 for t in labels if t == label)
        precision = tp / said if said else 0.0
        recall = tp / actual if actual else 0.0
        lines.append(f"| {label} | {precision:.0%} | {recall:.0%} | {actual} |")
    return "\n".join(lines)


def as_dict(rows: list[SweepRow]) -> list[dict[str, float]]:
    return [asdict(row) for row in rows]
