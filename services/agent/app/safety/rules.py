"""Tier 1: regex rules. About a millisecond, no model involved.

Privacy first: a card number, PIN or code said out loud is withheld before it
can reach the conversation history or any model. Then known attack phrases.
"""

import re

from app.safety.types import Label, ModerationResult

_LONG_NUMBER = re.compile(r"\b(?:\d[ -]?){8,19}\b")  # 8+ digits, spaces or dashes allowed
_SIN = re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{3}\b")  # Canadian social insurance number
_PIN_SHARED = re.compile(r"\b(pin|password|passcode)\b\D{0,15}\d{4,6}\b", re.IGNORECASE)
_ONE_TIME_CODE = re.compile(r"\b(code|otp)\b\D{0,15}\d{6}\b", re.IGNORECASE)
_INJECTION = re.compile(
    r"ignore (all |any |your |the )?(previous |prior |above )?(instructions|rules|prompt)"
    r"|system prompt|developer mode|you are now|pretend (to be|you are)"
    r"|act as (an? )?(admin|administrator|developer|bank employee)",
    re.IGNORECASE,
)

WITHHELD = "[message withheld]"


def passes_luhn(digits: str) -> bool:
    """The checksum every real card number passes."""
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def _sensitive(reason: str, reply: str, placeholder: str) -> ModerationResult:
    return ModerationResult(
        Label.SENSITIVE_DATA, "rules", reason, reply=reply, safe_text=placeholder
    )


class RulesModerator:
    def check(self, text: str) -> ModerationResult:
        for match in _LONG_NUMBER.finditer(text):
            digits = re.sub(r"\D", "", match.group())
            if 13 <= len(digits) <= 19 and passes_luhn(digits):
                return _sensitive(
                    "card_number",
                    "Please don't share your full card number. I'll never need it.",
                    "[card number withheld]",
                )
            if _SIN.fullmatch(match.group().strip()):
                return _sensitive(
                    "sin",
                    "Please don't share your social insurance number. I'll never need it.",
                    "[SIN withheld]",
                )
            return _sensitive(
                "account_number",
                "Please don't read out long numbers like account or card numbers. "
                "I'll refer to your accounts by type, like chequing or savings.",
                "[number withheld]",
            )
        if _PIN_SHARED.search(text):
            return _sensitive(
                "pin_shared",
                "Please don't say your PIN out loud. "
                "When I need it, you'll enter it on the keypad.",
                "[PIN withheld]",
            )
        if _ONE_TIME_CODE.search(text):
            return _sensitive(
                "code_shared",
                "Please don't say your one-time code here. I'll ask for it when it's needed.",
                "[code withheld]",
            )
        if _INJECTION.search(text):
            return ModerationResult(
                Label.PROMPT_INJECTION, "rules", "prompt_injection", safe_text=WITHHELD
            )
        return ModerationResult(Label.SAFE, "rules")
