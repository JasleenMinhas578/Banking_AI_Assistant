"""Answer from the policy documents: FAQ cache, then grounded RAG, never a guess."""

import logging
from typing import Any

from app.policy.answerer import PolicyAnswerer
from app.replies import POLICY_UNAVAILABLE
from app.state import ConversationState

log = logging.getLogger(__name__)


class PolicyAnswerNode:
    def __init__(self, answerer: PolicyAnswerer | None) -> None:
        self.answerer = answerer  # None until `make policies` has built the index

    async def run(self, state: ConversationState) -> dict[str, Any]:
        question = next(
            (t["text"] for t in reversed(state.get("messages", [])) if t["role"] == "caller"), ""
        )
        if self.answerer is None:
            return {"reply": POLICY_UNAVAILABLE, "policy": {"source": "unavailable"}}
        answer = await self.answerer.answer(question)
        # The policy id is kept for the trace, never read out loud.
        log.info(
            "policy source=%s policy=%s similarity=%s grounded=%s",
            answer.source,
            answer.policy_id,
            f"{answer.similarity:.2f}" if answer.similarity else "-",
            answer.grounded,
        )
        return {
            "reply": answer.text,
            "policy": {
                "source": answer.source,
                "policy_id": answer.policy_id,
                "similarity": answer.similarity,
                "grounded": answer.grounded,
            },
        }
