"""Respond: say one or two short sentences, then close the turn."""

from typing import Any

from app.replies import HELP, from_tool_result
from app.state import ConversationState


class ResponseNode:
    async def run(self, state: ConversationState) -> dict[str, Any]:
        reply = state.get("reply") or from_tool_result(state.get("tool_result")) or HELP
        return {
            "reply": reply,
            "messages": [{"role": "assistant", "text": reply}],
            # Nothing waits across turns: a yes can never apply to an old action.
            "pending_action": None,
            "confirmed": False,
            "tool_result": None,
        }
