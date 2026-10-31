"""Hybrid moderation: three tiers, cheapest first, on every caller turn.

    1. rules       regex for card numbers, PINs, codes and known attacks   ~1 ms
    2. classifier  scikit-learn, decides when it's confident enough        ~1 ms
    3. judge       Llama Guard 3 + bank checklist, only when tier 2 isn't sure

If tier 3 is down, the turn is marked unsure: it can still get a general
answer, but anything that touches an account goes to a person. The check is
never skipped. This module only labels; ModerationNode decides what to do.
"""

import logging
from typing import Protocol

from app.config import Settings
from app.safety.classifier import SklearnClassifier, TextClassifier
from app.safety.judge import Judge, JudgeUnavailable, OllamaJudge
from app.safety.rules import RulesModerator
from app.safety.types import Label, ModerationResult

__all__ = [
    "HybridModerator",
    "InputModerator",
    "Label",
    "ModerationResult",
    "RulesModerator",
    "build_moderator",
]

log = logging.getLogger(__name__)


class InputModerator(Protocol):
    async def check(self, text: str) -> ModerationResult: ...


class HybridModerator:
    def __init__(
        self, rules: RulesModerator, classifier: TextClassifier | None, judge: Judge | None
    ) -> None:
        self.rules = rules
        self.classifier = classifier
        self.judge = judge

    async def check(self, text: str) -> ModerationResult:
        result = await self._decide(text)
        # The label, tier and score are logged; the caller's words never are.
        log.info(
            "moderation label=%s tier=%s score=%s unsure=%s",
            result.label,
            result.tier,
            f"{result.score:.2f}" if result.score is not None else "-",
            result.unsure,
        )
        return result

    async def _decide(self, text: str) -> ModerationResult:
        ruled = self.rules.check(text)
        if ruled.label != Label.SAFE:
            return ruled

        guess = self.classifier.predict(text) if self.classifier else None
        if guess and self.classifier and guess.score >= self.classifier.threshold:
            return ModerationResult(guess.label, "classifier", score=guess.score)

        score = guess.score if guess else None
        if self.judge:
            try:
                return ModerationResult(await self.judge.judge(text), "judge", score=score)
            except JudgeUnavailable:
                pass

        # Tier 3 is down. Lean towards caution: a leaning-unsafe guess is acted on,
        # and a leaning-safe one is marked unsure so account actions go to a person.
        if guess and guess.label != Label.SAFE:
            return ModerationResult(guess.label, "fallback", score=score)
        return ModerationResult(Label.SAFE, "fallback", score=score, unsure=True)


def build_moderator(config: Settings) -> HybridModerator:
    return HybridModerator(
        RulesModerator(),
        SklearnClassifier.load(config.moderation_model_dir, config.moderation_threshold),
        OllamaJudge(config.guard_model, config.router_model, config.ollama_base_url),
    )
