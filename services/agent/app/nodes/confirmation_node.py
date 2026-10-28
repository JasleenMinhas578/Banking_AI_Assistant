"""Confirm: read the action back and pause until the caller answers.

Only a clear yes counts. Anything else cancels, because a half-yes is not a yes.
"""

from typing import Any

from langgraph.types import interrupt

from app.moderation import RulesModerator
from app.replies import CANCELLED
from app.routing import is_clear_yes
from app.state import ConversationState


class ConfirmationNode:
    def __init__(self, moderator: RulesModerator) -> None:
        self.moderator = moderator

    async def run(self, state: ConversationState) -> dict[str, Any]:
        action = state.get("pending_action") or {}
        answer = interrupt(
            {"kind": "confirm", "prompt": f"{action.get('summary', '')} Shall I go ahead?"}
        )
        said = self._safe_text(answer)
        if is_clear_yes(answer):
            return {"confirmed": True, "messages": [{"role": "caller", "text": said}]}
        return {
            "confirmed": False,
            "pending_action": None,
            "reply": CANCELLED,
            "messages": [{"role": "caller", "text": said}],
        }

    def _safe_text(self, answer: Any) -> str:
        """The answer is caller input too: never store a card number or PIN from it."""
        text = answer if isinstance(answer, str) else ""
        result = self.moderator.check(text)
        if result.verdict == "block":
            return result.safe_text or "[message withheld]"
        return text
