"""The real agent with real models: Ollama + MCP server + bank API + database.

Needs `make dev`, `make mcp` and Ollama running with the models pulled.
Skipped otherwise. Model answers vary, so these check outcomes, not wording.
"""

import uuid

import httpx2
import pytest

from app.agent import Agent
from app.chat import BankGateway
from app.config import settings
from app.graph import build_graph

pytestmark = pytest.mark.anyio


def everything_is_up() -> bool:
    checks = [f"{settings.bank_api_url}/health", f"{settings.ollama_base_url}/api/tags"]
    try:
        return all(httpx2.get(url, timeout=2).status_code == 200 for url in checks)
    except Exception:
        return False


@pytest.fixture
async def call() -> tuple[Agent, BankGateway]:
    if not everything_is_up():
        pytest.skip("Needs `make dev`, `make mcp` and Ollama running.")
    http = httpx2.AsyncClient(base_url=settings.bank_api_url, timeout=10)
    bank = BankGateway(http)
    token = await bank.start_session()
    agent = Agent(
        build_graph(settings),
        call_id=str(uuid.uuid4()),
        session_token=token,
        recursion_limit=settings.recursion_limit,
    )
    return agent, bank


async def test_balance_with_real_models(call: tuple[Agent, BankGateway]) -> None:
    agent, bank = call

    paused = await agent.say("Hi, how much money do I have?")
    assert paused.kind == "pin"
    reply = await agent.answer(await bank.verify_pin("C-1001", "2468"))

    assert "••••4821" in reply.text


async def test_transfer_with_real_models_stops_for_a_yes(call: tuple[Agent, BankGateway]) -> None:
    agent, bank = call
    await agent.say("what's my balance")
    await agent.answer(await bank.verify_pin("C-1001", "2468"))

    question = await agent.say("Please move $1 from chequing to savings")
    assert question.kind == "confirm"
    assert "$1.00" in question.text

    cancelled = await agent.answer("no")
    assert "cancelled" in cancelled.text
