"""Puffin Bank's MCP server: the bank's actions as tools an AI agent can call.

Run it:
    uv run python -m app.server                       # Streamable HTTP on :8100/mcp
    uv run python -m app.server --transport stdio     # for MCP Inspector / Claude Desktop

Who is the caller? The agent connects with its caller's bank session token in
an "Authorization: Bearer ..." header. The MCP server doesn't trust that token
itself: it forwards it on every bank API call, and the bank API checks it. The
model never sees the token, because Context isn't part of any tool's schema.

What's deliberately missing: no tool takes a PIN or a one-time code, and no tool
starts or verifies a session. Those happen outside the model, in the gateway.
"""

import argparse
from collections.abc import Awaitable
from datetime import timedelta
from typing import Annotated, Literal, TypeVar

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from app.bank_client import BankClient
from app.clock import utc_now
from app.config import Settings, settings
from app.refs import RefRegistry
from app.schemas import (
    AccountsResult,
    CardsResult,
    DisputesResult,
    FreezeCardResult,
    OpenDisputeResult,
    TransactionsResult,
    TransferQuoteResult,
    TransferResult,
)
from app.tools import BankTools, ToolFailure

T = TypeVar("T")

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
SAFE_TO_REPEAT = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
MOVES_MONEY = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
)

AccountRef = Annotated[str, Field(description="An account reference from get_accounts, e.g. 'A1'")]


def create_server(tools: BankTools, *, dev_session_token: str | None = None) -> MCPServer:
    """Build the MCP server around a BankTools instance.

    dev_session_token is only for stdio clients and tests, which can't send
    an Authorization header.
    """
    mcp = MCPServer("puffin-bank")

    def session_token(ctx: Context) -> str:
        for name, value in (ctx.headers or {}).items():
            if name.lower() == "authorization" and value.lower().startswith("bearer "):
                return str(value[7:].strip())
        if dev_session_token:
            return dev_session_token
        raise ToolError("no_session: this conversation has no verified bank session.")

    async def run(call: Awaitable[T]) -> T:
        try:
            return await call
        except ToolFailure as failure:
            raise ToolError(f"{failure.code}: {failure.message}") from failure

    @mcp.tool(annotations=READ_ONLY)
    async def get_accounts(ctx: Context) -> AccountsResult:
        """List the caller's accounts with masked numbers and balances.

        Call this first: it hands out the account references (A1, A2...) other tools need.
        """
        return await run(tools.get_accounts(session_token(ctx)))

    @mcp.tool(annotations=READ_ONLY)
    async def list_transactions(
        account_ref: AccountRef,
        ctx: Context,
        limit: Annotated[int, Field(ge=1, le=50, description="How many, newest first")] = 10,
    ) -> TransactionsResult:
        """Recent transactions on one of the caller's accounts, newest first.

        Each transaction gets a reference (T1, T2...) for open_dispute.
        """
        return await run(tools.list_transactions(session_token(ctx), account_ref, limit))

    @mcp.tool(annotations=READ_ONLY)
    async def list_cards(ctx: Context) -> CardsResult:
        """List the caller's debit cards, masked, with their status (active or frozen)."""
        return await run(tools.list_cards(session_token(ctx)))

    @mcp.tool(annotations=SAFE_TO_REPEAT)
    async def freeze_card(
        card_ref: Annotated[str, Field(description="A card reference from list_cards, e.g. 'C1'")],
        ctx: Context,
    ) -> FreezeCardResult:
        """Freeze one of the caller's cards immediately. Safe to repeat.

        Only call after the caller has confirmed which card. Unfreezing is not
        possible here: only a human agent can unfreeze a card.
        """
        return await run(tools.freeze_card(session_token(ctx), card_ref))

    @mcp.tool(annotations=READ_ONLY)
    async def list_disputes(ctx: Context) -> DisputesResult:
        """List the caller's disputes and where each one stands."""
        return await run(tools.list_disputes(session_token(ctx)))

    @mcp.tool(annotations=SAFE_TO_REPEAT)
    async def open_dispute(
        transaction_ref: Annotated[
            str, Field(description="A transaction reference from list_transactions, e.g. 'T3'")
        ],
        reason: Annotated[
            Literal["fraud", "wrong_amount", "duplicate_charge", "not_received"],
            Field(description="'fraud' if the caller didn't make the purchase"),
        ],
        ctx: Context,
    ) -> OpenDisputeResult:
        """Dispute a purchase. If one is already open for it, returns that one instead.

        Only purchases posted in the last 60 days can be disputed. If handoff is
        true, tell the caller a Puffin Bank agent will follow up.
        """
        return await run(tools.open_dispute(session_token(ctx), transaction_ref, reason))

    @mcp.tool(annotations=READ_ONLY)
    async def prepare_transfer(
        from_account_ref: AccountRef,
        to_account_ref: AccountRef,
        amount: Annotated[str, Field(description="In dollars, e.g. '200' or '1250.50'")],
        ctx: Context,
    ) -> TransferQuoteResult:
        """Step 1 of 2: check a transfer between the caller's own accounts. Moves nothing.

        Read the summary back to the caller, then wait for a clear "yes" before
        calling confirm_transfer.
        """
        return await run(
            tools.prepare_transfer(session_token(ctx), from_account_ref, to_account_ref, amount)
        )

    @mcp.tool(annotations=MOVES_MONEY)
    async def confirm_transfer(
        quote_ref: Annotated[str, Field(description="The quote_ref from prepare_transfer")],
        ctx: Context,
    ) -> TransferResult:
        """Step 2 of 2: move the money for a prepared transfer.

        Only call after the caller clearly said yes to the summary. Retrying is
        safe: the same quote can never move money twice.
        """
        return await run(tools.confirm_transfer(session_token(ctx), quote_ref))

    return mcp


def build_tools(config: Settings, http: httpx.AsyncClient) -> BankTools:
    """The real BankTools, talking to the bank API configured in settings."""
    return BankTools(
        bank=BankClient(http),
        registry=RefRegistry(timedelta(minutes=config.refs_idle_minutes), clock=utc_now),
        quote_ttl=timedelta(minutes=config.transfer_quote_minutes),
        step_up_threshold_cents=config.step_up_threshold_cents,
        clock=utc_now,
    )


def main() -> None:
    """Start the server over Streamable HTTP (default) or stdio."""
    parser = argparse.ArgumentParser(description="Puffin Bank MCP server")
    parser.add_argument(
        "--transport", choices=["streamable-http", "stdio"], default="streamable-http"
    )
    args = parser.parse_args()

    http = httpx.AsyncClient(base_url=settings.bank_api_url, timeout=settings.bank_timeout_seconds)
    mcp = create_server(build_tools(settings, http), dev_session_token=settings.bank_session_token)
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport="streamable-http", host=settings.mcp_host, port=settings.mcp_port)


if __name__ == "__main__":
    main()
