"""Checks the assistant's own reply before it is spoken.

Replies are templates today, so this is a backstop for tool messages and for
phase 5's policy answers: no long numbers, and no financial advice.
"""

import re

ADVICE_FALLBACK = (
    "I can't give financial advice, but I can help with your balances, transactions, "
    "cards, disputes and transfers."
)
_LONG_DIGITS = re.compile(r"\d{5,}")  # amounts are "$12,500.00"; card endings are "••••4821"
_ADVICE = re.compile(
    r"\byou should (invest|buy|sell)\b|\bi (would )?recommend (buying|selling|investing)\b"
    r"|\bguaranteed (return|profit)s?\b|\b(good|great|smart) investment\b",
    re.IGNORECASE,
)


def guard_reply(reply: str) -> str:
    if _ADVICE.search(reply):
        return ADVICE_FALLBACK
    return _LONG_DIGITS.sub(lambda m: "•" * len(m.group()), reply)
