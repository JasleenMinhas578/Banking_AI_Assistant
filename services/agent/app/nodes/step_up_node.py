"""Step-up code: for transfers over $1,000, the gateway collects a one-time code.

Like the PIN, the code never enters the graph. The gateway asks the bank to
send it, checks what the caller enters, and resumes with only the outcome:
{"verified": bool, "exhausted": bool, "cancelled": bool}.
"""

from typing import Any

from langgraph.types import interrupt

from app.replies import CODE_PROMPT, CODE_RETRY
from app.state import ConversationState


class StepUpNode:
    async def run(self, state: ConversationState) -> dict[str, Any]:
        attempts = state.get("step_up_attempts", 0)
        outcome = interrupt(
            {"kind": "one_time_code", "prompt": CODE_RETRY if attempts else CODE_PROMPT}
        )
        outcome = outcome if isinstance(outcome, dict) else {}

        if outcome.get("verified"):
            return {"step_up_verified": True, "step_up_attempts": 0}
        if outcome.get("exhausted") or outcome.get("cancelled"):
            return {
                "pending_action": None,
                "step_up_attempts": 0,
                "reply": "I couldn't verify the code, so I haven't moved any money.",
            }
        return {"step_up_attempts": attempts + 1}
