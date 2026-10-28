"""An in-memory bank that answers exactly like the bank API's JSON, for unit tests."""

from typing import Any
from uuid import UUID, uuid4

from app.bank_client import JSON, BankApiError

TOKEN = "priya-session-token"
CHEQUING, SAVINGS = uuid4(), uuid4()
COSTCO, AMAZON = uuid4(), uuid4()
CARD = uuid4()


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    dollars, rest = divmod(abs(cents), 100)
    return f"{sign}${dollars:,}.{rest:02d}"


class FakeBank:
    """Priya's accounts. Records every call so tests can check what was sent."""

    def __init__(self) -> None:
        self.balances = {CHEQUING: 324_050, SAVINGS: 1_250_000}
        self.card_status = "active"
        self.transfers: dict[str, JSON] = {}
        self.calls: list[tuple[str, Any]] = []
        self.fail_with: BankApiError | None = None

    def _check(self, token: str, name: str, detail: Any = None) -> None:
        self.calls.append((name, detail))
        if token != TOKEN:
            raise BankApiError(401, "session_invalid", "No valid session.")
        if self.fail_with is not None:
            raise self.fail_with

    def _account(self, account_id: UUID) -> JSON:
        kind, last4 = ("chequing", "4821") if account_id == CHEQUING else ("savings", "7710")
        cents = self.balances[account_id]
        return {
            "id": str(account_id),
            "account_type": kind,
            "masked_number": f"••••{last4}",
            "balance_cents": cents,
            "balance": money(cents),
        }

    async def get_accounts(self, token: str) -> list[JSON]:
        self._check(token, "get_accounts")
        return [self._account(CHEQUING), self._account(SAVINGS)]

    async def get_transactions(self, token: str, account_id: UUID, limit: int) -> JSON:
        self._check(token, "get_transactions", (account_id, limit))
        rows = [
            {
                "id": str(AMAZON),
                "merchant": "Amazon",
                "amount_cents": -5999,
                "amount": "-$59.99",
                "status": "pending",
                "posted_at": "2026-10-28T10:00:00+00:00",
            },
            {
                "id": str(COSTCO),
                "merchant": "Costco",
                "amount_cents": -18432,
                "amount": "-$184.32",
                "status": "posted",
                "posted_at": "2026-10-26T10:00:00+00:00",
            },
        ]
        return {"account": self._account(account_id), "transactions": rows[:limit]}

    def _card(self) -> JSON:
        return {
            "id": str(CARD),
            "account_id": str(CHEQUING),
            "masked_number": "••••9012",
            "status": self.card_status,
            "frozen_at": None,
        }

    async def get_cards(self, token: str) -> list[JSON]:
        self._check(token, "get_cards")
        return [self._card()]

    async def freeze_card(self, token: str, card_id: UUID) -> JSON:
        self._check(token, "freeze_card", card_id)
        changed = self.card_status == "active"
        self.card_status = "frozen"
        verb = "is now" if changed else "was already"
        return {
            "card": self._card(),
            "changed": changed,
            "message": f"Card ••••9012 {verb} frozen.",
        }

    def _dispute(self) -> JSON:
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "reference": "D-11111111",
            "transaction_id": str(COSTCO),
            "merchant": "Costco",
            "amount": "-$184.32",
            "reason": "fraud",
            "status": "open",
            "created_at": "2026-10-28T12:00:00+00:00",
        }

    async def get_disputes(self, token: str) -> list[JSON]:
        self._check(token, "get_disputes")
        return [self._dispute()]

    async def open_dispute(self, token: str, transaction_id: UUID, reason: str) -> JSON:
        self._check(token, "open_dispute", (transaction_id, reason))
        return {
            "dispute": self._dispute(),
            "created": True,
            "handoff": reason == "fraud",
            "message": "Dispute D-11111111 is now open for the $184.32 charge from Costco.",
        }

    async def create_transfer(
        self, token: str, from_id: UUID, to_id: UUID, amount_cents: int, idempotency_key: str
    ) -> JSON:
        self._check(token, "create_transfer", (from_id, to_id, amount_cents, idempotency_key))
        created = idempotency_key not in self.transfers
        if created:
            self.balances[from_id] -= amount_cents
            self.balances[to_id] += amount_cents
            self.transfers[idempotency_key] = {"reference": f"T-{len(self.transfers) + 1:08d}"}
        return {
            "transfer": self.transfers[idempotency_key],
            "from_account": self._account(from_id),
            "to_account": self._account(to_id),
            "created": created,
            "message": "Moved." if created else "Already done.",
        }
