"""Verify identity: pause the graph and let the gateway collect the PIN.

The PIN never enters the graph. The gateway switches to secure input, sends
the PIN straight to the bank API, and resumes the graph with only the outcome:
{"verified": bool, "locked": bool, "customer_code": str, "cancelled": bool}.
"""

from typing import Any

from langgraph.types import interrupt

from app.replies import PIN_PROMPT, PIN_RETRY
from app.state import ConversationState

PIN_ENTERED = {"role": "caller", "text": "[PIN entered]"}


class IdentityNode:
    def __init__(self, max_attempts: int) -> None:
        self.max_attempts = max_attempts

    async def run(self, state: ConversationState) -> dict[str, Any]:
        attempts = state.get("pin_attempts", 0)
        # Everything above interrupt() re-runs on resume, so it must stay side-effect free.
        outcome = interrupt({"kind": "pin", "prompt": PIN_RETRY if attempts else PIN_PROMPT})
        outcome = outcome if isinstance(outcome, dict) else {}

        if outcome.get("cancelled"):
            return {"reply": "No problem. I'll need your PIN before I can look at your accounts."}
        if outcome.get("verified"):
            return {
                "verified": True,
                "customer_code": outcome.get("customer_code"),
                "pin_attempts": 0,
                "messages": [PIN_ENTERED],
            }
        attempts += 1
        if outcome.get("locked") or attempts >= self.max_attempts:
            return {"pin_attempts": attempts, "handoff_reason": "pin_locked"}
        return {"pin_attempts": attempts, "messages": [PIN_ENTERED]}
