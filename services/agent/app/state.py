"""The conversation state the graph passes between nodes, and the fixed risk table.

Everything here is plain data (strings, numbers, dicts), so the checkpointer
can save it between turns. What the model may influence is limited to the
intent it suggests and the details it reads out of the conversation. Flags
like `verified` and `confirmed` are only ever set by code.
"""

from enum import StrEnum
from typing import Annotated, Any, TypedDict


class Intent(StrEnum):
    POLICY_QUESTION = "policy_question"
    BALANCE = "balance"
    TRANSACTIONS = "transactions"
    FREEZE_CARD = "freeze_card"
    DISPUTE = "dispute"
    TRANSFER = "transfer"
    HUMAN = "human"
    OTHER = "other"


class RiskTier(StrEnum):
    LOW = "low"  # no identity needed
    MEDIUM = "medium"  # verified caller, read-only
    HIGH = "high"  # verified + explicit yes
    HIGHEST = "highest"  # verified + yes + one-time code over $1,000 + bank limits


# Fixed in code, never chosen by the model: the model names an intent, this table
# decides how careful to be.
INTENT_RISK: dict[Intent, RiskTier] = {
    Intent.POLICY_QUESTION: RiskTier.LOW,
    Intent.OTHER: RiskTier.LOW,
    Intent.HUMAN: RiskTier.LOW,
    Intent.BALANCE: RiskTier.MEDIUM,
    Intent.TRANSACTIONS: RiskTier.MEDIUM,
    Intent.FREEZE_CARD: RiskTier.HIGH,
    Intent.DISPUTE: RiskTier.HIGH,
    Intent.TRANSFER: RiskTier.HIGHEST,
}


# The only tools that change anything. Everything else is read-only.
WRITE_TOOLS = frozenset({"freeze_card", "open_dispute", "confirm_transfer"})


class Turn(TypedDict):
    role: str  # "caller" or "assistant"
    text: str


def keep_recent_turns(existing: list[Turn], new: list[Turn]) -> list[Turn]:
    """Reducer: append new turns, keep only the last few (6 caller + 6 assistant)."""
    return (existing + new)[-12:]


class PendingAction(TypedDict, total=False):
    """The exact tool call waiting to run. Built by the planner, run by the tool node."""

    tool: str
    args: dict[str, Any]
    summary: str  # read back to the caller before anything changes
    needs_code: bool  # a transfer over $1,000


class ConversationState(TypedDict, total=False):
    # Set by the gateway when the call starts
    call_id: str
    session_token: str  # sent to the MCP server in a header; never shown to a model
    customer_code: str | None

    # This turn
    input: str  # the caller's words, before moderation decides whether to keep them
    reply: str | None  # what the assistant says at the end of the turn
    messages: Annotated[list[Turn], keep_recent_turns]

    # Gates, set only by code
    verified: bool
    step_up_verified: bool
    confirmed: bool

    # Routing
    intent: str | None
    risk_tier: str | None
    router_confidence: float
    awaiting: str | None  # the intent whose missing detail we just asked for

    # Planning and execution
    pending_action: PendingAction | None
    tool_result: dict[str, Any] | None

    # Counters that trigger a handoff
    pin_attempts: int
    clarify_count: int
    tool_failures: int
    step_up_attempts: int

    moderation: dict[str, Any]
    handoff_reason: str | None
    handoff_summary: dict[str, Any] | None
    ended: bool
