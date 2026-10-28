"""Verify identity: pause the graph and let the gateway collect the PIN.

The PIN never enters the graph. The gateway switches to secure input, sends
the PIN straight to the bank API, and resumes the graph with only the outcome:
{"verified": bool, "locked": bool, "customer_code": str, "cancelled": bool,
 "bad_format": bool}. A badly formatted PIN (not 4 digits) isn't counted as a try.
"""

from typing import Any

from langgraph.types import interrupt

from app.replies import PIN_FORMAT, PIN_PROMPT, PIN_RETRY
from app.state import ConversationState

PIN_ENTERED = {"role": "caller", "text": "[PIN entered]"}


class IdentityNode:
    def __init__(self, max_attempts: int) -> None:
        self.max_attempts = max_attempts

    async def run(self, state: ConversationState) -> dict[str, Any]:
        attempts = state.get("pin_attempts", 0)
        if state.get("pin_hint") == "bad_format":
            prompt = PIN_FORMAT
        else:
            prompt = PIN_RETRY if attempts else PIN_PROMPT
        # Everything above interrupt() re-runs on resume, so it must stay side-effect free.
        outcome = interrupt({"kind": "pin", "prompt": prompt})
        outcome = outcome if isinstance(outcome, dict) else {}

        if outcome.get("bad_format"):
            return {"pin_hint": "bad_format"}  # ask again; not a wrong PIN

        if outcome.get("cancelled"):
            return {
                "pin_hint": None,
                "reply": "No problem. I'll need your PIN before I can look at your accounts.",
            }
        if outcome.get("verified"):
            return {
                "pin_hint": None,
                "verified": True,
                "customer_code": outcome.get("customer_code"),
                "pin_attempts": 0,
                "messages": [PIN_ENTERED],
            }
        attempts += 1
        if outcome.get("locked") or attempts >= self.max_attempts:
            return {"pin_hint": None, "pin_attempts": attempts, "handoff_reason": "pin_locked"}
        return {"pin_hint": None, "pin_attempts": attempts, "messages": [PIN_ENTERED]}
