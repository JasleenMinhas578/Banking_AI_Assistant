"""Tier 2: the scikit-learn classifier trained in ml/moderation_classifier.

It decides only when its top label is at least as confident as the threshold
chosen at training time. Anything less goes on to tier 3.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.safety.types import Label

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Prediction:
    label: Label
    score: float  # probability of the top label


class TextClassifier(Protocol):
    threshold: float

    def predict(self, text: str) -> Prediction: ...


class SklearnClassifier:
    """The saved pipeline plus its threshold, from model/classifier.joblib + metadata.json."""

    def __init__(self, pipeline: Any, threshold: float) -> None:
        self._pipeline = pipeline
        self._labels = [Label(name) for name in pipeline.classes_]
        self.threshold = threshold

    @classmethod
    def load(cls, model_dir: Path, threshold: float | None = None) -> "SklearnClassifier | None":
        """None if the model hasn't been trained yet: the cascade then sends turns to tier 3."""
        model_file, metadata_file = model_dir / "classifier.joblib", model_dir / "metadata.json"
        if not (model_file.is_file() and metadata_file.is_file()):
            log.warning("No moderation classifier at %s; run `make moderation-train`", model_dir)
            return None
        import joblib  # imported here so the agent still starts without scikit-learn
        import sklearn

        metadata = json.loads(metadata_file.read_text())
        if metadata.get("sklearn_version") != sklearn.__version__:
            log.warning(
                "Classifier trained with scikit-learn %s, running %s; retrain if results look off",
                metadata.get("sklearn_version"),
                sklearn.__version__,
            )
        # joblib files are pickles: only ever load the one this repo trained.
        pipeline = joblib.load(model_file)
        return cls(pipeline, threshold if threshold is not None else float(metadata["threshold"]))

    def predict(self, text: str) -> Prediction:
        probabilities = self._pipeline.predict_proba([text])[0]
        best = int(probabilities.argmax())
        return Prediction(self._labels[best], float(probabilities[best]))
