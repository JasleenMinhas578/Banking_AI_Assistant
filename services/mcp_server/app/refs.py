"""Opaque references: the model sees 'A1' or 'T3', never a real account or transaction ID.

Why: real IDs are long UUIDs that models copy badly, and leaking them would
let a prompt-injected model probe other customers' data. Short references
only mean something inside one conversation, so there is nothing to probe.

Each conversation (one bank session) gets its own RefBook. References are
handed out in order (A1, A2...) and the same real ID always gets the same
reference within a conversation.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

Kind = Literal["A", "T", "C", "D"]  # Account, Transaction, Card, Dispute

KIND_NAMES: dict[str, str] = {
    "A": "account",
    "T": "transaction",
    "C": "card",
    "D": "dispute",
    "Q": "transfer",
}


class UnknownReference(LookupError):
    """The model used a reference this conversation never handed out."""


@dataclass
class TransferQuote:
    """A transfer the caller has been asked to confirm. Nothing has moved yet."""

    from_account_id: UUID
    to_account_id: UUID
    amount_cents: int
    summary: str
    expires_at: datetime
    # Made once, here, and reused on every confirm: a retried confirm can
    # never move the money twice.
    idempotency_key: str = field(default_factory=lambda: str(uuid4()))


@dataclass
class RefBook:
    """All references handed out in one conversation."""

    last_used: datetime
    _to_ref: dict[UUID, str] = field(default_factory=dict)
    _from_ref: dict[str, UUID] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)
    quotes: dict[str, TransferQuote] = field(default_factory=dict)

    def ref_for(self, kind: Kind, real_id: UUID) -> str:
        """The reference for a real ID, handing out a new one the first time."""
        if real_id in self._to_ref:
            return self._to_ref[real_id]
        ref = self._next(kind)
        self._to_ref[real_id] = ref
        self._from_ref[ref] = real_id
        return ref

    def resolve(self, kind: Kind, ref: str) -> UUID:
        """The real ID behind a reference, or UnknownReference."""
        cleaned = ref.strip().upper()
        if not cleaned.startswith(kind) or cleaned not in self._from_ref:
            raise UnknownReference(
                f"'{ref}' is not a {KIND_NAMES[kind]} reference from this conversation"
            )
        return self._from_ref[cleaned]

    def add_quote(self, quote: TransferQuote) -> str:
        """Store a prepared transfer and return its reference, like 'Q1'."""
        ref = self._next("Q")
        self.quotes[ref] = quote
        return ref

    def _next(self, prefix: str) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}{self._counters[prefix]}"


class RefRegistry:
    """One RefBook per conversation, forgotten after a period of inactivity.

    Keyed by a hash of the session token, so raw tokens aren't kept around
    as dictionary keys. Lives in memory: restarting the server clears it,
    and the agent simply lists accounts again.
    """

    def __init__(self, idle_timeout: timedelta, clock: Callable[[], datetime]) -> None:
        self.idle_timeout = idle_timeout
        self.clock = clock
        self._books: dict[str, RefBook] = {}

    def book_for(self, session_token: str) -> RefBook:
        """The RefBook for this conversation, created on first use."""
        now = self.clock()
        self._forget_idle(now)
        key = hashlib.sha256(session_token.encode()).hexdigest()
        book = self._books.setdefault(key, RefBook(last_used=now))
        book.last_used = now
        return book

    def _forget_idle(self, now: datetime) -> None:
        stale = [k for k, b in self._books.items() if now - b.last_used > self.idle_timeout]
        for key in stale:
            del self._books[key]
