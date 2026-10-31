"""Fixed sentences and templates. Results that are facts are never paraphrased by a model."""

import re
from typing import Any

HELP = (
    "I can help with your balances, recent transactions, freezing a card, "
    "disputing a charge, or moving money between your own accounts."
)
CLARIFY = (
    "Sorry, I want to get this right. Is it about your balance or transactions, "
    "a card, a charge you don't recognise, or moving money?"
)
POLICY_UNAVAILABLE = (
    "I can't look up our policies right now. I can connect you with a Puffin Bank agent, "
    "or help with your accounts, cards, disputes and transfers."
)
PIN_PROMPT = "For your security, please enter your 4-digit PIN on the keypad."
PIN_RETRY = "That PIN didn't match. Please try again on the keypad."
PIN_FORMAT = "PINs are exactly 4 digits. Please enter yours on the keypad."
CODE_PROMPT = (
    "Transfers over $1,000 need a one-time code. I've sent one to your phone. "
    "Please enter it on the keypad."
)
CODE_RETRY = "That code didn't match. Please try again."
CANCELLED = "Okay, I've cancelled that. Nothing has changed."

# Moderation replies, by label
INJECTION_REFUSAL = "I can't do that. " + HELP
SOCIAL_ENGINEERING = (
    "For everyone's security, I can only help account holders with their own accounts, "
    "and everyone verifies themselves with their own PIN. I can't share or change anyone "
    "else's details."
)
ABUSE_WARNING = (
    "I want to help, but I can't continue if the language stays abusive. "
    "What can I do for you today?"
)
OFF_TOPIC = "That's outside what I can help with. " + HELP

HANDOFF = {
    "pin_locked": "For your security, I've locked access after too many PIN attempts. "
    "I'm connecting you with a Puffin Bank agent now.",
    "unclear_request": "Let me connect you with a Puffin Bank agent who can help.",
    "requested": "Of course. I'm connecting you with a Puffin Bank agent now.",
    "distress": "I'm sorry you're going through this. I'm connecting you with a person at "
    "Puffin Bank right now. If you're in danger or thinking about harming yourself, please "
    "call 911, or call or text 988 for the Suicide Crisis Helpline.",
    "abuse": "I'm going to pass this call to a Puffin Bank agent now.",
    "repeated_attacks": "I can't help with this call, so I'm passing it to a Puffin Bank agent.",
    "safety_check_unavailable": "I can't safely handle account requests right now, so I'm "
    "connecting you with a Puffin Bank agent.",
    "default": "I'm connecting you with a Puffin Bank agent now. "
    "They'll have a summary, so you won't need to repeat yourself.",
}
REASON_WORDS = {
    "fraud": "a purchase you didn't make",
    "wrong_amount": "the wrong amount",
    "duplicate_charge": "a double charge",
    "not_received": "something you paid for but didn't receive",
}


def accounts_reply(data: dict[str, Any]) -> str:
    parts = [f"your {a['type']} {a['number']} has {a['balance']}" for a in data["accounts"]]
    if not parts:
        return "I couldn't find any accounts."
    sentence = ", and ".join(parts)
    return sentence[0].upper() + sentence[1:] + "."


def transactions_reply(data: dict[str, Any]) -> str:
    account = data["account"]
    rows = data["transactions"]
    if not rows:
        return f"There's no recent activity on your {account['type']} {account['number']}."
    items = [
        f"{t['merchant']} {t['amount']}" + (" (pending)" if t["status"] == "pending" else "")
        for t in rows
    ]
    return (
        f"Your last {len(rows)} on {account['type']} {account['number']}: " + "; ".join(items) + "."
    )


def from_tool_result(result: dict[str, Any] | None) -> str | None:
    """The sentence to say for a tool's result, or None if there's no result."""
    if not result:
        return None
    tool, data = result["tool"], result["data"]
    if tool == "get_accounts":
        return accounts_reply(data)
    if tool == "list_transactions":
        return transactions_reply(data)
    message = data.get("message")
    return str(message) if message else "Done."


def mask_digits(text: str) -> str:
    """Hide any run of 4+ digits except masked card endings, for handoff notes."""
    return re.sub(r"(?<!•)\d{4,}", lambda m: "•" * len(m.group()), text)
