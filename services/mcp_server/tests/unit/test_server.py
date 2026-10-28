"""The tools as an MCP client sees them: names, schemas, results and errors.

Uses the SDK's in-memory Client, so no port or subprocess is needed.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from mcp import Client

from app.refs import RefRegistry
from app.server import create_server
from app.tools import BankTools
from tests.unit.fake_bank import TOKEN, FakeBank

pytestmark = pytest.mark.anyio

EXPECTED_TOOLS = {
    "get_accounts",
    "list_transactions",
    "list_cards",
    "freeze_card",
    "list_disputes",
    "open_dispute",
    "prepare_transfer",
    "confirm_transfer",
}


def make_tools(bank: FakeBank) -> BankTools:
    def now() -> datetime:
        return datetime(2026, 10, 28, 12, 0, tzinfo=UTC)

    return BankTools(
        bank=bank,
        registry=RefRegistry(timedelta(minutes=30), now),
        quote_ttl=timedelta(minutes=5),
        step_up_threshold_cents=100_000,
        clock=now,
    )


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    server = create_server(make_tools(FakeBank()), dev_session_token=TOKEN)
    async with Client(server, raise_exceptions=True) as connected:
        yield connected


async def test_exactly_the_expected_tools_exist(client: Client) -> None:
    listed = await client.list_tools()

    assert {tool.name for tool in listed.tools} == EXPECTED_TOOLS


async def test_no_tool_asks_for_a_pin_code_or_token(client: Client) -> None:
    listed = await client.list_tools()

    for tool in listed.tools:
        params = set(tool.input_schema.get("properties", {}))
        assert not params & {"pin", "otp", "code", "token", "session", "ctx"}, tool.name


async def test_only_confirm_transfer_is_marked_destructive(client: Client) -> None:
    listed = await client.list_tools()

    destructive = {
        tool.name for tool in listed.tools if tool.annotations and tool.annotations.destructive_hint
    }
    assert destructive == {"confirm_transfer"}


async def test_get_accounts_returns_structured_refs(client: Client) -> None:
    result = await client.call_tool("get_accounts", {})

    assert result.is_error is False
    assert result.structured_content is not None
    assert [a["ref"] for a in result.structured_content["accounts"]] == ["A1", "A2"]


async def test_two_step_transfer_over_mcp(client: Client) -> None:
    await client.call_tool("get_accounts", {})
    quote = await client.call_tool(
        "prepare_transfer", {"from_account_ref": "A1", "to_account_ref": "A2", "amount": "200"}
    )
    assert quote.structured_content is not None

    done = await client.call_tool(
        "confirm_transfer", {"quote_ref": quote.structured_content["quote_ref"]}
    )

    assert done.structured_content is not None
    assert done.structured_content["created"] is True


async def test_refusals_come_back_as_tool_errors_with_a_code(client: Client) -> None:
    result = await client.call_tool("freeze_card", {"card_ref": "C9"})

    assert result.is_error is True
    assert "unknown_reference" in result.content[0].text


async def test_bad_arguments_are_rejected_before_the_tool_runs(client: Client) -> None:
    result = await client.call_tool(
        "open_dispute", {"transaction_ref": "T1", "reason": "i changed my mind"}
    )

    assert result.is_error is True


async def test_without_a_session_every_tool_refuses() -> None:
    server = create_server(make_tools(FakeBank()))  # no dev token, and no HTTP headers here
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("get_accounts", {})

    assert result.is_error is True
    assert "no_session" in result.content[0].text
