"""The routing table and the gates, including the path test from the design doc:
no combination of state may ever reach "execute" without the right gates."""

import itertools
from typing import Any

import pytest

from app.routing import Routes, gate_allows, is_clear_yes
from app.state import WRITE_TOOLS, ConversationState, Intent, RiskTier

ROUTES = Routes(min_confidence=0.7)
TOOLS = ["get_accounts", "list_transactions", "freeze_card", "open_dispute", "confirm_transfer"]


@pytest.mark.parametrize("answer", ["yes", "Yes.", "yeah", "Go ahead!", "  confirm  ", "do it"])
def test_clear_yes(answer: str) -> None:
    assert is_clear_yes(answer)


@pytest.mark.parametrize(
    "answer",
    ["yes, and also move $500", "no", "maybe", "yes but to chequing", "sure why not", "", None, 1],
)
def test_anything_else_is_not_a_yes(answer: Any) -> None:
    assert not is_clear_yes(answer)


def all_states() -> list[ConversationState]:
    """Every combination of the gate flags, tools and code requirement."""
    states: list[ConversationState] = []
    for verified, confirmed, stepped_up, needs_code, tool in itertools.product(
        [False, True], [False, True], [False, True], [False, True], TOOLS
    ):
        states.append(
            {
                "verified": verified,
                "confirmed": confirmed,
                "step_up_verified": stepped_up,
                "pending_action": {"tool": tool, "args": {}, "needs_code": needs_code},
            }
        )
    return states


def test_a_write_never_goes_straight_from_planning_to_execution() -> None:
    for state in all_states():
        action = state["pending_action"] or {}
        if ROUTES.after_plan(state) == "execute":
            assert action["tool"] not in WRITE_TOOLS


def test_a_transfer_needing_a_code_goes_to_step_up_first() -> None:
    state: ConversationState = {
        "verified": True,
        "step_up_verified": False,
        "pending_action": {"tool": "confirm_transfer", "args": {}, "needs_code": True},
    }
    assert ROUTES.after_plan(state) == "step_up"


def test_the_gate_lets_nothing_through_unverified() -> None:
    for state in all_states():
        if not state["verified"]:
            assert not gate_allows(state, dict(state["pending_action"] or {}))


def test_the_gate_needs_a_yes_for_every_write() -> None:
    for state in all_states():
        action = dict(state["pending_action"] or {})
        if action["tool"] in WRITE_TOOLS and not state["confirmed"]:
            assert not gate_allows(state, action)


def test_the_gate_needs_the_code_for_big_transfers() -> None:
    for state in all_states():
        action = dict(state["pending_action"] or {})
        if action["needs_code"] and not state["step_up_verified"]:
            assert not gate_allows(state, action)


def test_the_gate_allows_the_fully_checked_case() -> None:
    state: ConversationState = {"verified": True, "confirmed": True, "step_up_verified": True}
    assert gate_allows(state, {"tool": "confirm_transfer", "needs_code": True})


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"intent": Intent.HUMAN, "router_confidence": 0.9}, "handoff"),
        ({"intent": Intent.BALANCE, "router_confidence": 0.5}, "clarify"),
        (
            {"intent": Intent.POLICY_QUESTION, "router_confidence": 0.9, "risk_tier": RiskTier.LOW},
            "policy_answer",
        ),
        ({"intent": Intent.OTHER, "router_confidence": 0.9, "risk_tier": RiskTier.LOW}, "respond"),
        (
            {
                "intent": Intent.BALANCE,
                "router_confidence": 0.9,
                "risk_tier": RiskTier.MEDIUM,
                "verified": False,
            },
            "verify",
        ),
        (
            {
                "intent": Intent.TRANSFER,
                "router_confidence": 0.9,
                "risk_tier": RiskTier.HIGHEST,
                "verified": True,
            },
            "plan",
        ),
        ({"handoff_reason": "model_unavailable"}, "handoff"),
    ],
)
def test_after_route(state: ConversationState, expected: str) -> None:
    assert ROUTES.after_route(state) == expected


def test_after_confirm_only_executes_on_a_yes() -> None:
    assert ROUTES.after_confirm({"confirmed": True}) == "execute"
    assert ROUTES.after_confirm({"confirmed": False}) == "respond"
    assert ROUTES.after_confirm({}) == "respond"


def test_after_verify() -> None:
    assert ROUTES.after_verify({"verified": True}) == "plan"
    assert ROUTES.after_verify({"verified": False}) == "verify"
    assert ROUTES.after_verify({"handoff_reason": "pin_locked"}) == "handoff"
    assert ROUTES.after_verify({"reply": "No problem."}) == "respond"
