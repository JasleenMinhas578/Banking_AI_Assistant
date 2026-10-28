"""Clarify: ask one either/or question instead of guessing. Hand off after two."""

from typing import Any

from app.replies import CLARIFY
from app.state import ConversationState


class ClarifyNode:
    def __init__(self, max_clarifications: int) -> None:
        self.max_clarifications = max_clarifications

    async def run(self, state: ConversationState) -> dict[str, Any]:
        count = state.get("clarify_count", 0) + 1
        if count > self.max_clarifications:
            return {"clarify_count": count, "handoff_reason": "unclear_request"}
        return {"clarify_count": count, "reply": CLARIFY}
