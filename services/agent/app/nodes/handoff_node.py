"""Hand off: write a masked summary for the human agent and end the call."""

from typing import Any

from app.replies import HANDOFF, mask_digits
from app.state import ConversationState


class HandoffNode:
    async def run(self, state: ConversationState) -> dict[str, Any]:
        reason = state.get("handoff_reason") or "requested"
        reply = HANDOFF.get(reason, HANDOFF["default"])
        recent = state.get("messages", [])[-6:]
        summary = {
            "reason": reason,
            "intent": state.get("intent"),
            "verified": bool(state.get("verified")),
            "customer_code": state.get("customer_code"),
            "recent": [f"{t['role']}: {mask_digits(t['text'])}" for t in recent],
        }
        return {
            "reply": reply,
            "messages": [{"role": "assistant", "text": reply}],
            "handoff_summary": summary,
            "pending_action": None,
            "confirmed": False,
            "ended": True,
        }
