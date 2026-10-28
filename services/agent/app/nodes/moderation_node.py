"""Moderate input: decides whether the caller's words may enter the conversation at all."""

from typing import Any

from app.moderation import RulesModerator
from app.state import ConversationState

# Reset at the start of every turn, so nothing from the last turn leaks into this one.
FRESH_TURN: dict[str, Any] = {
    "reply": None,
    "pending_action": None,
    "confirmed": False,
    "tool_result": None,
    "handoff_reason": None,
}


class ModerationNode:
    def __init__(self, moderator: RulesModerator) -> None:
        self.moderator = moderator

    async def run(self, state: ConversationState) -> dict[str, Any]:
        text = state.get("input", "")
        result = self.moderator.check(text)
        update: dict[str, Any] = {**FRESH_TURN, "input": ""}  # the raw text isn't kept
        if result.verdict == "block":
            return {
                **update,
                "moderation": {"verdict": "block", "reason": result.reason, "tier": "rules"},
                "messages": [{"role": "caller", "text": result.safe_text}],
                "reply": result.reply,
            }
        return {
            **update,
            "moderation": {"verdict": "pass", "tier": "rules"},
            "messages": [{"role": "caller", "text": text}],
        }
