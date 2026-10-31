"""What every tier returns, and the labels they share with the classifier."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Label(StrEnum):
    """Same names as ml/moderation_classifier/labels.py."""

    SAFE = "safe"
    PROMPT_INJECTION = "prompt_injection"
    SOCIAL_ENGINEERING = "social_engineering"
    ABUSE = "abuse"
    DISTRESS = "distress"
    OFF_TOPIC = "off_topic"
    SENSITIVE_DATA = "sensitive_data"  # rules only: a card number, PIN or code was said


Tier = Literal["rules", "classifier", "judge", "fallback"]


@dataclass(frozen=True)
class ModerationResult:
    label: Label
    tier: Tier
    reason: str | None = None  # the specific rule, e.g. "card_number", "prompt_injection"
    score: float | None = None  # the classifier's confidence, when it decided
    reply: str | None = None  # rules only: what to say back
    safe_text: str | None = None  # rules only: what may be kept in the history instead
    unsure: bool = False  # tier 3 was needed but didn't answer

    @property
    def verdict(self) -> Literal["pass", "block"]:
        return "pass" if self.label == Label.SAFE else "block"
