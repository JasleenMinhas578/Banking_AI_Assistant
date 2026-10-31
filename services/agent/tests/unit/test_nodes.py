"""Each node on its own, with fake models and tools. interrupt() is replaced per test."""

from typing import Any

import pytest

from app.llm import ModelUnavailable
from app.moderation import RulesModerator
from app.nodes import confirmation_node, identity_node, step_up_node
from app.nodes.handoff_node import HandoffNode
from app.nodes.moderation_node import ModerationNode
from app.nodes.planner_node import ActionPlannerNode
from app.nodes.router_node import RouterNode
from app.nodes.tool_node import ToolNode
from app.state import ConversationState, Intent
from app.toolbox import ToolCallError
from tests.unit.fakes import FakeExtractor, FakeRouter, FakeTools, fake_moderator

pytestmark = pytest.mark.anyio


def answers(monkeypatch: pytest.MonkeyPatch, module: Any, *values: Any) -> list[Any]:
    """Make interrupt() in `module` return these values in order; returns the prompts."""
    prompts: list[Any] = []
    queue = list(values)

    def fake_interrupt(payload: Any) -> Any:
        prompts.append(payload)
        return queue.pop(0)

    monkeypatch.setattr(module, "interrupt", fake_interrupt)
    return prompts


def verified(intent: Intent, **extra: Any) -> ConversationState:
    state: ConversationState = {"verified": True, "session_token": "tok", "intent": intent.value}
    state.update(extra)  # type: ignore[typeddict-item]
    return state


def planner(tools: FakeTools, **details: dict[str, Any]) -> ActionPlannerNode:
    return ActionPlannerNode(FakeExtractor(**details), tools, transactions_to_show=5)


# ---- moderation and routing ---------------------------------------------------


async def test_blocked_input_never_enters_the_history() -> None:
    update = await ModerationNode(fake_moderator()).run({"input": "my PIN is 2468"})

    assert update["moderation"]["verdict"] == "block"
    assert update["messages"] == [{"role": "caller", "text": "[PIN withheld]"}]
    assert update["input"] == ""
    assert "2468" not in str(update)


async def test_a_short_answer_continues_the_awaited_request() -> None:
    state: ConversationState = {
        "awaiting": "transactions",
        "messages": [{"role": "caller", "text": "chequing"}],
    }

    update = await RouterNode(FakeRouter(), 0.7).run(state)

    assert (update["intent"], update["awaiting"]) == ("transactions", None)


async def test_a_clear_new_request_beats_the_awaited_one() -> None:
    state: ConversationState = {
        "awaiting": "transactions",
        "messages": [{"role": "caller", "text": "actually, freeze my card"}],
    }

    update = await RouterNode(FakeRouter(), 0.7).run(state)

    assert update["intent"] == "freeze_card"


# ---- planning -----------------------------------------------------------------


async def test_planner_never_calls_a_tool_that_changes_data() -> None:
    tools = FakeTools()
    details = {
        "transfer": {"to_account": "savings", "amount": "200"},
        "dispute": {"merchant": "costco", "reason": "fraud"},
    }
    for intent in (Intent.BALANCE, Intent.FREEZE_CARD, Intent.DISPUTE, Intent.TRANSFER):
        await planner(tools, **details).run(verified(intent))

    assert tools.writes == []


async def test_transfer_to_savings_infers_from_chequing() -> None:
    update = await planner(FakeTools(), transfer={"to_account": "savings", "amount": "200"}).run(
        verified(Intent.TRANSFER)
    )

    action = update["pending_action"]
    assert action["tool"] == "confirm_transfer"
    assert action["summary"] == "Move $200.00 from chequing ••••4821 to savings ••••7710."
    assert action["needs_code"] is False


async def test_big_transfer_needs_a_code() -> None:
    update = await planner(FakeTools(), transfer={"to_account": "savings", "amount": "1500"}).run(
        verified(Intent.TRANSFER)
    )

    assert update["pending_action"]["needs_code"] is True


@pytest.mark.parametrize(
    ("details", "question"),
    [
        ({"to_account": "savings"}, "How much"),
        ({"from_account": "savings", "to_account": "savings", "amount": "5"}, "different"),
    ],
)
async def test_transfer_asks_for_what_is_missing(details: dict[str, Any], question: str) -> None:
    update = await planner(FakeTools(), transfer=details).run(verified(Intent.TRANSFER))

    assert question in update["reply"]
    assert update.get("awaiting") == "transfer"


async def test_transactions_ask_which_account() -> None:
    update = await planner(FakeTools()).run(verified(Intent.TRANSACTIONS))

    assert update["reply"] == "Which account: chequing or savings?"


async def test_freeze_the_only_active_card() -> None:
    update = await planner(FakeTools()).run(verified(Intent.FREEZE_CARD))

    assert update["pending_action"]["args"] == {"card_ref": "C1"}


async def test_already_frozen_card() -> None:
    tools = FakeTools()
    tools.card_status = "frozen"

    update = await planner(tools).run(verified(Intent.FREEZE_CARD))

    assert "already frozen" in update["reply"]


async def test_dispute_finds_the_charge() -> None:
    update = await planner(FakeTools(), dispute={"merchant": "Costco", "reason": "fraud"}).run(
        verified(Intent.DISPUTE)
    )

    action = update["pending_action"]
    assert action["args"] == {"transaction_ref": "T2", "reason": "fraud"}
    assert action["summary"] == (
        "I'll dispute the $184.32 charge from Costco on 2026-10-26 as a purchase you didn't make."
    )


async def test_pending_charge_cannot_be_disputed_yet() -> None:
    update = await planner(FakeTools(), dispute={"merchant": "amazon", "reason": "fraud"}).run(
        verified(Intent.DISPUTE)
    )

    assert "still pending" in update["reply"]


async def test_planner_refuses_an_unverified_caller() -> None:
    tools = FakeTools()
    state = verified(Intent.BALANCE, verified=False)

    update = await planner(tools).run(state)

    assert update["reply"] == "I need to confirm it's you first."
    assert tools.calls == []


async def test_bank_refusal_while_planning_is_explained() -> None:
    tools = FakeTools()
    tools.fail_with, tools.fail_times = ToolCallError("insufficient_funds", "Not enough."), 1

    update = await planner(tools, transfer={"to_account": "savings", "amount": "5"}).run(
        verified(Intent.TRANSFER)
    )

    assert update["reply"] == "Not enough."


async def test_model_down_hands_off() -> None:
    class BrokenExtractor:
        async def extract(self, intent: Intent, conversation: Any) -> Any:
            raise ModelUnavailable("ollama is down")

    node = ActionPlannerNode(BrokenExtractor(), FakeTools(), 5)

    update = await node.run(verified(Intent.TRANSFER))

    assert update["handoff_reason"] == "model_unavailable"


# ---- identity, step-up, confirmation ------------------------------------------


async def test_correct_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    answers(monkeypatch, identity_node, {"verified": True, "customer_code": "C-1001"})

    update = await identity_node.IdentityNode(3).run({})

    assert update["verified"] is True
    assert update["messages"] == [{"role": "caller", "text": "[PIN entered]"}]


async def test_badly_formatted_pin_is_not_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = answers(monkeypatch, identity_node, {"verified": False, "bad_format": True})

    update = await identity_node.IdentityNode(3).run({"pin_attempts": 1})

    assert update == {"pin_hint": "bad_format"}
    assert "didn't match" in prompts[0]["prompt"]


async def test_after_a_bad_format_the_prompt_explains(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = answers(monkeypatch, identity_node, {"verified": True})

    await identity_node.IdentityNode(3).run({"pin_hint": "bad_format"})

    assert prompts[0]["prompt"].startswith("PINs are exactly 4 digits")


async def test_third_wrong_pin_hands_off(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = answers(monkeypatch, identity_node, {"verified": False})

    update = await identity_node.IdentityNode(3).run({"pin_attempts": 2})

    assert update["handoff_reason"] == "pin_locked"
    assert "didn't match" in prompts[0]["prompt"]


async def test_wrong_code_asks_again_and_exhausted_cancels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers(monkeypatch, step_up_node, {"verified": False}, {"exhausted": True})
    node = step_up_node.StepUpNode()

    first = await node.run({})
    second = await node.run({"step_up_attempts": 1})

    assert first == {"step_up_attempts": 1}
    assert second["pending_action"] is None
    assert "haven't moved any money" in second["reply"]


@pytest.mark.parametrize(
    ("said", "confirmed"), [("yes", True), ("Go ahead.", True), ("yes, and $500 more", False)]
)
async def test_confirmation(monkeypatch: pytest.MonkeyPatch, said: str, confirmed: bool) -> None:
    answers(monkeypatch, confirmation_node, said)
    state: ConversationState = {"pending_action": {"tool": "freeze_card", "summary": "Freeze?"}}

    update = await confirmation_node.ConfirmationNode(RulesModerator()).run(state)

    assert update["confirmed"] is confirmed
    if not confirmed:
        assert update["pending_action"] is None


async def test_card_number_at_confirmation_is_not_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    answers(monkeypatch, confirmation_node, "4111 1111 1111 1111")

    update = await confirmation_node.ConfirmationNode(RulesModerator()).run({"pending_action": {}})

    assert update["messages"] == [{"role": "caller", "text": "[card number withheld]"}]


# ---- execution and handoff ----------------------------------------------------


async def test_tool_node_refuses_an_unconfirmed_write() -> None:
    tools = FakeTools()
    state = verified(Intent.FREEZE_CARD, pending_action={"tool": "freeze_card", "args": {}})

    update = await ToolNode(tools).run(state)

    assert update["handoff_reason"] == "gate_violation"
    assert tools.calls == []


async def test_tool_node_retries_once_when_tools_dont_answer() -> None:
    tools = FakeTools()
    tools.fail_with, tools.fail_times = ToolCallError("tools_unavailable", "down"), 1
    state = verified(
        Intent.FREEZE_CARD,
        confirmed=True,
        pending_action={"tool": "freeze_card", "args": {"card_ref": "C1"}},
    )

    update = await ToolNode(tools).run(state)

    assert update["tool_result"]["data"]["changed"] is True
    assert len(tools.calls) == 2


async def test_tool_node_hands_off_after_two_failures() -> None:
    tools = FakeTools()
    tools.fail_with, tools.fail_times = ToolCallError("tools_unavailable", "down"), 2
    state = verified(Intent.BALANCE, pending_action={"tool": "get_accounts", "args": {}})

    update = await ToolNode(tools).run(state)

    assert update["handoff_reason"] == "tools_unavailable"


async def test_handoff_summary_is_masked() -> None:
    state: ConversationState = {
        "handoff_reason": "pin_locked",
        "messages": [{"role": "caller", "text": "my account 12345678 please"}],
    }

    update = await HandoffNode().run(state)

    assert update["ended"] is True
    assert "12345678" not in str(update["handoff_summary"])
