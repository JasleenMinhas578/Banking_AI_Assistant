"""Plan the action: turn the caller's words into one exact tool call, or one question.

The model only reads details out of the conversation ("savings", "$200").
Code does the rest: looks up references, fills gaps it safely can, asks for
the one it can't, and builds `pending_action`. It works through a read-only
toolbox, so planning can never change anything at the bank.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from app.llm import (
    DetailExtractor,
    DisputeDetails,
    FreezeDetails,
    ModelUnavailable,
    TransactionsDetails,
    TransferDetails,
)
from app.replies import REASON_WORDS
from app.state import ConversationState, Intent
from app.toolbox import ReadOnlyToolbox, Toolbox, ToolboxFactory, ToolCallError

Plan = dict[str, Any]


def ask(intent: Intent, question: str) -> Plan:
    """End the turn with one question, and remember what we're waiting for."""
    return {"reply": question, "awaiting": intent.value}


class ActionPlannerNode:
    def __init__(
        self, extractor: DetailExtractor, toolboxes: ToolboxFactory, transactions_to_show: int
    ) -> None:
        self.extractor = extractor
        self.toolboxes = toolboxes
        self.transactions_to_show = transactions_to_show
        self._plans: dict[Intent, Callable[[Any, Toolbox], Awaitable[Plan]]] = {
            Intent.BALANCE: self._balance,
            Intent.TRANSACTIONS: self._transactions,
            Intent.FREEZE_CARD: self._freeze_card,
            Intent.DISPUTE: self._dispute,
            Intent.TRANSFER: self._transfer,
        }

    async def run(self, state: ConversationState) -> dict[str, Any]:
        if not state.get("verified"):  # routing already guarantees this; check anyway
            return {"reply": "I need to confirm it's you first."}
        intent = Intent(state["intent"])
        plan_for = self._plans.get(intent)
        if plan_for is None:
            return {"reply": None}
        tools = ReadOnlyToolbox(self.toolboxes(state["session_token"]))
        try:
            details = await self.extractor.extract(intent, state.get("messages", []))
            return await plan_for(details, tools)
        except ModelUnavailable:
            return {"handoff_reason": "model_unavailable"}
        except ToolCallError as error:
            return refusal(error)

    async def _balance(self, details: BaseModel, tools: Toolbox) -> Plan:
        return {"pending_action": {"tool": "get_accounts", "args": {}}}

    async def _transactions(self, details: TransactionsDetails, tools: Toolbox) -> Plan:
        accounts = (await tools.call("get_accounts", {}))["accounts"]
        account = pick_account(accounts, details.account)
        if account is None:
            return ask(Intent.TRANSACTIONS, "Which account: chequing or savings?")
        args = {"account_ref": account["ref"], "limit": self.transactions_to_show}
        return {"pending_action": {"tool": "list_transactions", "args": args}}

    async def _freeze_card(self, details: FreezeDetails, tools: Toolbox) -> Plan:
        cards = (await tools.call("list_cards", {}))["cards"]
        if details.card_last4:
            matches = [c for c in cards if c["number"].endswith(details.card_last4)]
            if not matches:
                endings = ", ".join(c["number"][-4:] for c in cards)
                return ask(
                    Intent.FREEZE_CARD,
                    f"I couldn't find a card ending in {details.card_last4}. "
                    f"Your cards end in {endings}. Which one?",
                )
            cards = matches
        active = [c for c in cards if c["status"] == "active"]
        if not active:
            return {"reply": "That card is already frozen, so it can't be used."}
        if len(active) > 1:
            endings = " or ".join(c["number"][-4:] for c in active)
            return ask(
                Intent.FREEZE_CARD, f"Which card should I freeze: the one ending in {endings}?"
            )
        card = active[0]
        return {
            "pending_action": {
                "tool": "freeze_card",
                "args": {"card_ref": card["ref"]},
                "summary": f"I'll freeze your card ending in {card['number'][-4:]}. "
                "Only a Puffin Bank agent can unfreeze it.",
            }
        }

    async def _dispute(self, details: DisputeDetails, tools: Toolbox) -> Plan:
        if not details.merchant:
            return ask(Intent.DISPUTE, "Which charge would you like to dispute? Who was it from?")
        charge = await find_charge(tools, details.merchant)
        if charge is None:
            return {"reply": f"I couldn't find a recent charge from {details.merchant}."}
        if charge["status"] == "pending":
            return {"reply": "That charge is still pending. It can be disputed once it posts."}
        if not details.reason:
            return ask(
                Intent.DISPUTE,
                "Is this a purchase you didn't make, the wrong amount, a double charge, "
                "or something you never received?",
            )
        amount = charge["amount"].lstrip("-")
        return {
            "pending_action": {
                "tool": "open_dispute",
                "args": {"transaction_ref": charge["ref"], "reason": details.reason},
                "summary": f"I'll dispute the {amount} charge from {charge['merchant']} "
                f"on {charge['date']} as {REASON_WORDS[details.reason]}.",
            }
        }

    async def _transfer(self, details: TransferDetails, tools: Toolbox) -> Plan:
        accounts = (await tools.call("get_accounts", {}))["accounts"]
        source_type, target_type = fill_in_other_account(
            accounts, details.from_account, details.to_account
        )
        if not details.amount:
            return ask(Intent.TRANSFER, "How much would you like to move?")
        if not source_type or not target_type:
            return ask(Intent.TRANSFER, "From which account to which: chequing or savings?")
        if source_type == target_type:
            return ask(Intent.TRANSFER, "The two accounts need to be different. Which way?")
        source = pick_account(accounts, source_type)
        target = pick_account(accounts, target_type)
        if source is None or target is None:
            return {"reply": "You need both a chequing and a savings account for that."}
        quote = await tools.call(
            "prepare_transfer",
            {
                "from_account_ref": source["ref"],
                "to_account_ref": target["ref"],
                "amount": details.amount,
            },
        )
        return {
            "pending_action": {
                "tool": "confirm_transfer",
                "args": {"quote_ref": quote["quote_ref"]},
                "summary": quote["summary"],
                "needs_code": bool(quote["needs_one_time_code"]),
            }
        }


def pick_account(accounts: list[dict[str, Any]], account_type: str | None) -> dict[str, Any] | None:
    """The account of that type; or the only account, if there's just one."""
    if account_type:
        return next((a for a in accounts if a["type"] == account_type), None)
    return accounts[0] if len(accounts) == 1 else None


def fill_in_other_account(
    accounts: list[dict[str, Any]], source: str | None, target: str | None
) -> tuple[str | None, str | None]:
    """'Move $200 to savings' with exactly two account types means from chequing."""
    types = sorted({a["type"] for a in accounts})
    if len(types) == 2:
        if source and not target and source in types:
            target = next(t for t in types if t != source)
        elif target and not source and target in types:
            source = next(t for t in types if t != target)
    return source, target


async def find_charge(tools: Toolbox, merchant: str) -> dict[str, Any] | None:
    """The most recent charge (money out) whose merchant matches, across all accounts."""
    wanted = merchant.casefold().strip()
    matches: list[dict[str, Any]] = []
    for account in (await tools.call("get_accounts", {}))["accounts"]:
        result = await tools.call("list_transactions", {"account_ref": account["ref"], "limit": 50})
        matches += [
            t
            for t in result["transactions"]
            if wanted in t["merchant"].casefold() and t["amount"].startswith("-")
        ]
    return max(matches, key=lambda t: t["date"], default=None)


def refusal(error: ToolCallError) -> dict[str, Any]:
    """Turn a tool refusal into what happens next."""
    if error.code in {"session_expired", "session_invalid"}:
        return {"reply": "Your session has timed out. Please call back to continue.", "ended": True}
    if error.code == "verification_required":
        return {"verified": False, "reply": "I need to confirm it's you again first."}
    if error.code in {"tools_unavailable", "bank_unavailable", "bank_error", "tool_error"}:
        return {"handoff_reason": "tools_unavailable"}
    return {"reply": error.message}
