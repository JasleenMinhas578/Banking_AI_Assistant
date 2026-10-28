"""End to end: MCP client -> MCP server -> real bank API -> real database.

Needs the bank API running (`make dev` in another terminal) and seeded demo
data (`make seed`). Skipped otherwise. These tests change demo data a little
(a $1.00 transfer, a frozen card), so `make seed` resets everything.
"""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from mcp import Client

from app.config import settings
from app.money import parse_dollars
from app.server import build_tools, create_server

pytestmark = pytest.mark.anyio


def bank_is_up() -> bool:
    try:
        return httpx.get(f"{settings.bank_api_url}/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def verified_token(customer_code: str, pin: str) -> str:
    """Start a bank session and pass the PIN check, as the gateway will."""
    with httpx.Client(base_url=settings.bank_api_url, timeout=5) as http:
        token = str(http.post("/sessions").json()["session_token"])
        verified = http.post(
            "/sessions/verify",
            headers={"Authorization": f"Bearer {token}"},
            json={"customer_code": customer_code, "pin": pin},
        )
        assert verified.status_code == 200, verified.text
    return token


async def connect(token: str) -> AsyncIterator[Client]:
    async with httpx.AsyncClient(base_url=settings.bank_api_url, timeout=5) as http:
        server = create_server(build_tools(settings, http), dev_session_token=token)
        async with Client(server, raise_exceptions=True) as client:
            yield client


@pytest.fixture
async def priya() -> AsyncIterator[Client]:
    if not bank_is_up():
        pytest.skip("The bank API isn't running. Start it with `make dev`.")
    async for client in connect(verified_token("C-1001", "2468")):
        yield client


@pytest.fixture
async def unverified() -> AsyncIterator[Client]:
    if not bank_is_up():
        pytest.skip("The bank API isn't running. Start it with `make dev`.")
    with httpx.Client(base_url=settings.bank_api_url, timeout=5) as http:
        token = str(http.post("/sessions").json()["session_token"])
    async for client in connect(token):
        yield client


def data(result: Any) -> dict[str, Any]:
    assert result.is_error is False, result.content
    content: dict[str, Any] = result.structured_content
    return content


async def test_priya_sees_her_accounts_masked(priya: Client) -> None:
    accounts = data(await priya.call_tool("get_accounts", {}))["accounts"]

    assert [(a["ref"], a["number"]) for a in accounts] == [("A1", "••••4821"), ("A2", "••••7710")]


async def test_transfer_round_trip_moves_one_dollar_once(priya: Client) -> None:
    before = data(await priya.call_tool("get_accounts", {}))["accounts"]
    quote = data(
        await priya.call_tool(
            "prepare_transfer", {"from_account_ref": "A1", "to_account_ref": "A2", "amount": "1"}
        )
    )

    first = data(await priya.call_tool("confirm_transfer", {"quote_ref": quote["quote_ref"]}))
    again = data(await priya.call_tool("confirm_transfer", {"quote_ref": quote["quote_ref"]}))
    after = data(await priya.call_tool("get_accounts", {}))["accounts"]

    assert (first["created"], again["created"]) == (True, False)
    assert first["reference"] == again["reference"]
    assert _cents(before[0]["balance"]) - _cents(after[0]["balance"]) == 100


async def test_big_transfer_needs_a_one_time_code(priya: Client) -> None:
    await priya.call_tool("get_accounts", {})
    quote = data(
        await priya.call_tool(
            "prepare_transfer",
            {"from_account_ref": "A2", "to_account_ref": "A1", "amount": "1500"},
        )
    )
    assert quote["needs_one_time_code"] is True

    result = await priya.call_tool("confirm_transfer", {"quote_ref": quote["quote_ref"]})

    assert result.is_error is True
    assert "step_up_required" in result.content[0].text


async def test_unverified_caller_gets_nothing(unverified: Client) -> None:
    result = await unverified.call_tool("get_accounts", {})

    assert result.is_error is True
    assert "verification_required" in result.content[0].text


def _cents(balance: str) -> int:
    return parse_dollars(balance)
