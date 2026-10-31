"""Phase 7: the gateway collects PINs and codes itself and the agent only learns the outcome."""

import uuid
from typing import Any

import pytest

pytest.importorskip("langgraph.graph")

from app.agent import Agent  # noqa: E402
from app.config import Settings  # noqa: E402
from app.gateway.calls import Call, CallStore  # noqa: E402
from app.gateway.speech import spoken  # noqa: E402
from app.graph import build_graph  # noqa: E402
from tests.unit.fakes import (  # noqa: E402
    FakeAnswerer,
    FakeExtractor,
    FakeJudge,
    FakeRouter,
    FakeTools,
    fake_moderator,
)

pytestmark = pytest.mark.anyio


class FakeBank:
    """Stands in for the bank's session endpoints."""

    def __init__(self) -> None:
        self.pins: list[str] = []
        self.codes_sent = 0

    async def start_session(self) -> str:
        return "tok"

    async def verify_pin(self, customer_code: str, pin: str) -> dict[str, Any]:
        self.pins.append(pin)
        return {"verified": pin == "2468", "locked": False, "customer_code": customer_code}

    async def send_code(self) -> str:
        self.codes_sent += 1
        return "048213"

    async def verify_code(self, code: str) -> dict[str, Any]:
        return {"verified": code == "048213", "exhausted": False}


def store_with(**details: Any) -> tuple[CallStore, Call, FakeBank, FakeTools]:
    tools = FakeTools()
    store = CallStore.__new__(CallStore)
    store.config = Settings()
    from app.tracing import Tracer

    store.tracer = Tracer(None)
    store.graph = build_graph(
        store.config,
        router=FakeRouter(),
        extractor=FakeExtractor(**details),
        toolboxes=tools,
        moderator=fake_moderator(FakeJudge()),
        answerer=FakeAnswerer(),
        tracer=store.tracer,
    )
    store.calls = {}
    bank = FakeBank()
    agent = Agent(store.graph, call_id=str(uuid.uuid4()), session_token="tok", recursion_limit=12)
    call = Call(agent.call_id, "C-1001", "Priya Sharma", agent, bank)  # type: ignore[arg-type]
    store.calls[call.call_id] = call
    return store, call, bank, tools


async def test_pin_goes_to_the_bank_and_the_reply_carries_a_trace() -> None:
    store, call, bank, _ = store_with()

    paused = await store.say(call, "what's my balance?")
    reply = await store.pin(call, "2468")

    assert paused.kind == "pin"
    assert bank.pins == ["2468"]
    assert "$3,240.50" in reply.text
    assert reply.trace and [s["node"] for s in reply.trace["spans"]][0] == "moderate"
    assert "2468" not in str(reply.trace)


async def test_big_transfer_sends_the_demo_code_with_the_pause() -> None:
    store, call, bank, tools = store_with(
        transfer={"from_account": "savings", "to_account": "chequing", "amount": "1500"}
    )
    await store.say(call, "move $1500 from savings to chequing")
    code_pause = await store.pin(call, "2468")
    confirm = await store.code(call, "048213")
    done = await store.confirm(call, "yes")

    assert (code_pause.kind, code_pause.demo_code, bank.codes_sent) == (
        "one_time_code",
        "048213",
        1,
    )
    assert confirm.kind == "confirm"
    assert done.text.startswith("Moved") and tools.writes == ["confirm_transfer"]


async def test_an_ended_call_is_removed() -> None:
    store, call, _, _ = store_with()

    reply = await store.say(call, "can I talk to a person?")

    assert reply.ended and call.call_id not in store.calls


def test_masked_endings_are_read_digit_by_digit() -> None:
    assert spoken("savings ••••7710") == "savings ending 7 7 1 0"
