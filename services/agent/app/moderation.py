"""Phase 3's starter moderation: fast rules only.

Phase 4 adds the scikit-learn classifier and Llama Guard behind these rules.
Even this first tier matters for privacy: a card number or PIN typed into the
chat is withheld before it can reach the conversation history or any model.
"""

import re
from dataclasses import dataclass
from typing import Literal

Verdict = Literal["pass", "block"]

_CARD_NUMBER = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PIN_SHARED = re.compile(r"\b(pin|password|passcode)\b\D{0,15}\d{4,6}\b", re.IGNORECASE)
_ONE_TIME_CODE = re.compile(r"\b(code|otp)\b\D{0,15}\d{6}\b", re.IGNORECASE)
_INJECTION = re.compile(
    r"ignore (all |any |your |the )?(previous |prior |above )?(instructions|rules|prompt)"
    r"|system prompt|developer mode|you are now|pretend (to be|you are)"
    r"|act as (an? )?(admin|administrator|developer|bank employee)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ModerationResult:
    verdict: Verdict
    reason: str | None = None
    reply: str | None = None  # what to say back when blocked
    safe_text: str | None = None  # what may be kept in the conversation history


class RulesModerator:
    """Regex rules: about a millisecond, no model involved."""

    def check(self, text: str) -> ModerationResult:
        if _CARD_NUMBER.search(text):
            return ModerationResult(
                "block",
                "card_number",
                "Please don't share your full card number. I'll never need it.",
                "[card number withheld]",
            )
        if _PIN_SHARED.search(text):
            return ModerationResult(
                "block",
                "pin_shared",
                "Please don't say your PIN out loud. "
                "When I need it, you'll enter it on the keypad.",
                "[PIN withheld]",
            )
        if _ONE_TIME_CODE.search(text):
            return ModerationResult(
                "block",
                "code_shared",
                "Please don't say your one-time code here. I'll ask for it when it's needed.",
                "[code withheld]",
            )
        if _INJECTION.search(text):
            return ModerationResult(
                "block",
                "prompt_injection",
                "I can't do that. I can help with balances, transactions, cards, "
                "disputes or transfers between your own accounts.",
                "[message withheld]",
            )
        return ModerationResult("pass")
