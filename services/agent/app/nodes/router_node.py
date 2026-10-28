"""Route: the small model names an intent; a fixed table decides the risk tier."""

from typing import Any

from app.llm import IntentRouter, ModelUnavailable
from app.state import INTENT_RISK, ConversationState, Intent


class RouterNode:
    def __init__(self, router: IntentRouter, min_confidence: float) -> None:
        self.router = router
        self.min_confidence = min_confidence

    async def run(self, state: ConversationState) -> dict[str, Any]:
        try:
            decision = await self.router.classify(state.get("messages", []))
        except ModelUnavailable:
            return {"handoff_reason": "model_unavailable"}

        intent, confidence = decision.intent, decision.confidence
        awaiting = state.get("awaiting")
        # We just asked for a missing detail ("which account?"). A short answer like
        # "chequing" carries on that request, unless the caller clearly changed topic.
        if awaiting and (confidence < self.min_confidence or intent in (Intent.OTHER, awaiting)):
            intent, confidence = Intent(awaiting), 1.0

        update: dict[str, Any] = {
            "intent": intent.value,
            "risk_tier": INTENT_RISK[intent].value,
            "router_confidence": confidence,
            "awaiting": None,
        }
        if confidence >= self.min_confidence:
            update["clarify_count"] = 0
        return update
