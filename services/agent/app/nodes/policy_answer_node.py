"""Answer from policies. Phase 5 plugs RAG in here; until then it says so honestly."""

from typing import Any

from app.replies import POLICY_NOT_YET
from app.state import ConversationState


class PolicyAnswerNode:
    async def run(self, state: ConversationState) -> dict[str, Any]:
        return {"reply": POLICY_NOT_YET}
