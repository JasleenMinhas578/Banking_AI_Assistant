"""Every decision about where the graph goes next, as plain functions.

Kept apart from LangGraph so they can be tested exhaustively: the path test
checks that no combination of state ever reaches "execute" without the gates.
"""

from typing import Any

from app.state import WRITE_TOOLS, ConversationState, Intent, RiskTier

CLEAR_YES = frozenset(
    {"yes", "yeah", "yep", "yes please", "go ahead", "confirm", "yes go ahead", "do it"}
)


def is_clear_yes(answer: Any) -> bool:
    """Only an unambiguous yes counts. 'Yes, and also move $500' is not a yes."""
    if not isinstance(answer, str):
        return False
    words = "".join(ch for ch in answer.lower() if ch.isalpha() or ch.isspace())
    return " ".join(words.split()) in CLEAR_YES


def gate_allows(state: ConversationState, action: dict[str, Any]) -> bool:
    """The last check before any tool runs. Duplicates the routing on purpose.

    - Every bank tool needs a verified caller.
    - Anything that changes data needs an explicit yes.
    - A transfer over $1,000 also needs the one-time code.
    """
    if not state.get("verified"):
        return False
    if action.get("tool") in WRITE_TOOLS and not state.get("confirmed"):
        return False
    return not (action.get("needs_code") and not state.get("step_up_verified"))


class Routes:
    """The routing table from the design doc, one method per decision point."""

    def __init__(self, min_confidence: float) -> None:
        self.min_confidence = min_confidence

    @staticmethod
    def after_moderation(state: ConversationState) -> str:
        if state.get("handoff_reason"):  # distress, repeated abuse or attacks
            return "handoff"
        blocked = state.get("moderation", {}).get("verdict") == "block"
        return "respond" if blocked else "route"

    def after_route(self, state: ConversationState) -> str:
        if state.get("handoff_reason") or state.get("intent") == Intent.HUMAN:
            return "handoff"
        if state.get("router_confidence", 0.0) < self.min_confidence:
            return "clarify"
        if state.get("intent") == Intent.POLICY_QUESTION:
            return "policy_answer"
        if state.get("risk_tier") == RiskTier.LOW:
            return "respond"
        if state.get("moderation", {}).get("unsure"):  # the router node sets the reason too
            return "handoff"
        return "plan" if state.get("verified") else "verify"

    @staticmethod
    def after_clarify(state: ConversationState) -> str:
        return "handoff" if state.get("handoff_reason") else "respond"

    @staticmethod
    def after_verify(state: ConversationState) -> str:
        if state.get("handoff_reason"):
            return "handoff"
        if state.get("verified"):
            return "plan"
        if state.get("reply"):  # the caller cancelled
            return "respond"
        return "verify"  # wrong PIN: ask again

    @staticmethod
    def after_plan(state: ConversationState) -> str:
        if state.get("handoff_reason"):
            return "handoff"
        action = state.get("pending_action")
        if state.get("reply") or not action:
            return "respond"
        if action.get("tool") not in WRITE_TOOLS:
            return "execute"  # read-only: balances, transactions
        if action.get("needs_code") and not state.get("step_up_verified"):
            return "step_up"
        return "confirm"

    @staticmethod
    def after_step_up(state: ConversationState) -> str:
        if state.get("step_up_verified"):
            return "confirm"
        if state.get("reply") or not state.get("pending_action"):
            return "respond"
        return "step_up"  # wrong code: ask again

    @staticmethod
    def after_confirm(state: ConversationState) -> str:
        return "execute" if state.get("confirmed") else "respond"

    @staticmethod
    def after_execute(state: ConversationState) -> str:
        return "handoff" if state.get("handoff_reason") else "respond"
