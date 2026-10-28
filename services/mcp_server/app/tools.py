"""The logic behind each MCP tool, kept free of MCP itself so it's easy to test.

Every method takes the caller's session token, asks the bank API, and turns
the answer into a masked, reference-only view for the agent. Any refusal
becomes a ToolFailure with the bank's error code, which server.py hands back
to the model as a tool error.

Transfers take two calls on purpose:
  1. prepare_transfer: checks the details and returns a summary. Nothing moves.
  2. confirm_transfer: moves the money, only after the caller has said yes.
The agent's graph (phase 3) decides when confirm_transfer may be called.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Literal, TypeVar
from uuid import UUID

from app.bank_client import JSON, BankApi, BankApiError
from app.money import AmountError, format_cents, parse_dollars
from app.refs import RefBook, RefRegistry, TransferQuote, UnknownReference
from app.schemas import (
    AccountsResult,
    AccountView,
    CardsResult,
    CardView,
    DisputesResult,
    DisputeView,
    FreezeCardResult,
    OpenDisputeResult,
    TransactionsResult,
    TransactionView,
    TransferQuoteResult,
    TransferResult,
)

DisputeReason = Literal["fraud", "wrong_amount", "duplicate_charge", "not_received"]
T = TypeVar("T")


class ToolFailure(Exception):
    """A refusal the agent should hear about, with a stable code it can act on."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class BankTools:
    """One instance serves every conversation; each gets its own references."""

    def __init__(
        self,
        *,
        bank: BankApi,
        registry: RefRegistry,
        quote_ttl: timedelta,
        step_up_threshold_cents: int,
        clock: Callable[[], datetime],
    ) -> None:
        self.bank = bank
        self.registry = registry
        self.quote_ttl = quote_ttl
        self.step_up_threshold_cents = step_up_threshold_cents
        self.clock = clock

    # ---- reads -------------------------------------------------------------

    async def get_accounts(self, token: str) -> AccountsResult:
        book = self.registry.book_for(token)
        accounts = await self._ask(self.bank.get_accounts(token))
        return AccountsResult(accounts=[self._account(book, a) for a in accounts])

    async def list_transactions(
        self, token: str, account_ref: str, limit: int
    ) -> TransactionsResult:
        book = self.registry.book_for(token)
        account_id = self._resolve(book, "A", account_ref)
        body = await self._ask(self.bank.get_transactions(token, account_id, limit))
        return TransactionsResult(
            account=self._account(book, body["account"]),
            transactions=[self._transaction(book, t) for t in body["transactions"]],
        )

    async def list_cards(self, token: str) -> CardsResult:
        book = self.registry.book_for(token)
        cards = await self._ask(self.bank.get_cards(token))
        return CardsResult(cards=[self._card(book, c) for c in cards])

    async def list_disputes(self, token: str) -> DisputesResult:
        book = self.registry.book_for(token)
        disputes = await self._ask(self.bank.get_disputes(token))
        return DisputesResult(disputes=[self._dispute(book, d) for d in disputes])

    # ---- actions -----------------------------------------------------------

    async def freeze_card(self, token: str, card_ref: str) -> FreezeCardResult:
        book = self.registry.book_for(token)
        card_id = self._resolve(book, "C", card_ref)
        body = await self._ask(self.bank.freeze_card(token, card_id))
        return FreezeCardResult(
            card=self._card(book, body["card"]), changed=body["changed"], message=body["message"]
        )

    async def open_dispute(
        self, token: str, transaction_ref: str, reason: DisputeReason
    ) -> OpenDisputeResult:
        book = self.registry.book_for(token)
        transaction_id = self._resolve(book, "T", transaction_ref)
        body = await self._ask(self.bank.open_dispute(token, transaction_id, reason))
        return OpenDisputeResult(
            dispute=self._dispute(book, body["dispute"]),
            created=body["created"],
            handoff=body["handoff"],
            message=body["message"],
        )

    async def prepare_transfer(
        self, token: str, from_account_ref: str, to_account_ref: str, amount: str
    ) -> TransferQuoteResult:
        """Check the details and describe the transfer. Moves nothing."""
        book = self.registry.book_for(token)
        from_id = self._resolve(book, "A", from_account_ref)
        to_id = self._resolve(book, "A", to_account_ref)
        if from_id == to_id:
            raise ToolFailure("same_account", "The two accounts must be different.")
        try:
            amount_cents = parse_dollars(amount)
        except AmountError as exc:
            raise ToolFailure("invalid_amount", str(exc)) from exc

        accounts = {a["id"]: a for a in await self._ask(self.bank.get_accounts(token))}
        source, target = accounts.get(str(from_id)), accounts.get(str(to_id))
        if source is None or target is None:
            raise ToolFailure("account_not_found", "Call get_accounts again for fresh references.")
        if source["balance_cents"] < amount_cents:
            # The bank would refuse this too; saying so now spares the caller a pointless "yes".
            raise ToolFailure(
                "insufficient_funds",
                f"The {source['account_type']} account only has {source['balance']}.",
            )

        summary = f"Move {format_cents(amount_cents)} from {_label(source)} to {_label(target)}."
        quote_ref = book.add_quote(
            TransferQuote(
                from_account_id=from_id,
                to_account_id=to_id,
                amount_cents=amount_cents,
                summary=summary,
                expires_at=self.clock() + self.quote_ttl,
            )
        )
        return TransferQuoteResult(
            quote_ref=quote_ref,
            summary=summary,
            needs_one_time_code=amount_cents > self.step_up_threshold_cents,
            expires_in_minutes=int(self.quote_ttl.total_seconds() // 60),
        )

    async def confirm_transfer(self, token: str, quote_ref: str) -> TransferResult:
        """Move the money for a prepared transfer. Safe to retry: it can't move twice."""
        book = self.registry.book_for(token)
        quote = book.quotes.get(quote_ref.strip().upper())
        if quote is None:
            raise ToolFailure(
                "unknown_reference", f"'{quote_ref}' is not a prepared transfer. Prepare it first."
            )
        if self.clock() >= quote.expires_at:
            raise ToolFailure(
                "quote_expired", "This transfer waited too long. Prepare it again and re-confirm."
            )
        body = await self._ask(
            self.bank.create_transfer(
                token,
                quote.from_account_id,
                quote.to_account_id,
                quote.amount_cents,
                quote.idempotency_key,
            )
        )
        return TransferResult(
            reference=body["transfer"]["reference"],
            created=body["created"],
            message=body["message"],
            from_account=self._account(book, body["from_account"]),
            to_account=self._account(book, body["to_account"]),
        )

    # ---- helpers -----------------------------------------------------------

    async def _ask(self, call: Awaitable[T]) -> T:
        """Await a bank call, turning its refusals into ToolFailure."""
        try:
            return await call
        except BankApiError as exc:
            raise ToolFailure(exc.code, exc.message) from exc

    @staticmethod
    def _resolve(book: RefBook, kind: Literal["A", "T", "C", "D"], ref: str) -> UUID:
        try:
            return book.resolve(kind, ref)
        except UnknownReference as exc:
            hint = {
                "A": "Call get_accounts first.",
                "T": "Call list_transactions first.",
                "C": "Call list_cards first.",
                "D": "Call list_disputes first.",
            }[kind]
            raise ToolFailure("unknown_reference", f"{exc} {hint}") from exc

    @staticmethod
    def _account(book: RefBook, a: JSON) -> AccountView:
        return AccountView(
            ref=book.ref_for("A", _uuid(a["id"])),
            type=a["account_type"],
            number=a["masked_number"],
            balance=a["balance"],
        )

    @staticmethod
    def _transaction(book: RefBook, t: JSON) -> TransactionView:
        return TransactionView(
            ref=book.ref_for("T", _uuid(t["id"])),
            merchant=t["merchant"],
            amount=t["amount"],
            status=t["status"],
            date=str(t["posted_at"])[:10],
        )

    @staticmethod
    def _card(book: RefBook, c: JSON) -> CardView:
        return CardView(
            ref=book.ref_for("C", _uuid(c["id"])),
            number=c["masked_number"],
            status=c["status"],
            account_ref=book.ref_for("A", _uuid(c["account_id"])),
        )

    @staticmethod
    def _dispute(book: RefBook, d: JSON) -> DisputeView:
        return DisputeView(
            ref=book.ref_for("D", _uuid(d["id"])),
            reference=d["reference"],
            merchant=d["merchant"],
            amount=d["amount"],
            reason=d["reason"],
            status=d["status"],
            opened=str(d["created_at"])[:10],
        )


def _uuid(value: object) -> UUID:
    return UUID(str(value))


def _label(account: JSON) -> str:
    """'chequing ••••4821'."""
    return f"{account['account_type']} {account['masked_number']}"
