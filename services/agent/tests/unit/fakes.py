"""Stand-ins for the models and the bank's tools, so the agent runs without Ollama or MCP.

FakeTools answers exactly like the MCP server's tools (refs, masked numbers),
for Priya's demo data, and records every call.
"""

import zlib
from typing import Any

from pydantic import BaseModel

from app.llm import DETAILS_FOR, NoDetails, RouteDecision
from app.moderation import HybridModerator, RulesModerator
from app.safety.classifier import Prediction
from app.safety.judge import JudgeUnavailable
from app.safety.types import Label
from app.state import WRITE_TOOLS, Intent, Turn
from app.toolbox import ToolCallError


def last_caller_text(conversation: list[Turn]) -> str:
    return next((t["text"] for t in reversed(conversation) if t["role"] == "caller"), "")


class FakeRouter:
    """Routes by keywords in the caller's last message, like a well-behaved model."""

    RULES: list[tuple[str, Intent]] = [
        ("person", Intent.HUMAN),
        ("fee", Intent.POLICY_QUESTION),
        ("balance", Intent.BALANCE),
        ("transactions", Intent.TRANSACTIONS),
        ("freeze", Intent.FREEZE_CARD),
        ("lost", Intent.FREEZE_CARD),
        ("dispute", Intent.DISPUTE),
        ("move", Intent.TRANSFER),
        ("transfer", Intent.TRANSFER),
        ("hello", Intent.OTHER),
    ]

    def __init__(self) -> None:
        self.calls = 0

    async def classify(self, conversation: list[Turn]) -> RouteDecision:
        self.calls += 1
        text = last_caller_text(conversation).lower()
        for keyword, intent in self.RULES:
            if keyword in text:
                return RouteDecision(intent=intent, confidence=0.95)
        return RouteDecision(intent=Intent.OTHER, confidence=0.3)


class FakeExtractor:
    """Returns details set by the test, per intent (empty details by default)."""

    def __init__(self, **details: dict[str, Any]) -> None:
        self.details = details

    async def extract(self, intent: Intent, conversation: list[Turn]) -> BaseModel:
        schema = DETAILS_FOR.get(intent, NoDetails)
        return schema.model_validate(self.details.get(intent.value, {}))


class FakeTools:
    """Priya's accounts as the MCP server shows them."""

    def __init__(self) -> None:
        self.balances = {"A1": 324_050, "A2": 1_250_000}
        self.card_status = "active"
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_with: ToolCallError | None = None
        self.fail_times = 0
        self.done_quotes: set[str] = set()

    def __call__(self, session_token: str) -> "FakeTools":  # acts as its own factory
        return self

    @property
    def writes(self) -> list[str]:
        return [name for name, _ in self.calls if name in WRITE_TOOLS]

    def _account(self, ref: str) -> dict[str, Any]:
        kind, number = ("chequing", "••••4821") if ref == "A1" else ("savings", "••••7710")
        cents = self.balances[ref]
        return {"ref": ref, "type": kind, "number": number, "balance": f"${cents / 100:,.2f}"}

    async def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, args))
        if self.fail_with and self.fail_times > 0:
            self.fail_times -= 1
            raise self.fail_with
        if tool == "get_accounts":
            return {"accounts": [self._account("A1"), self._account("A2")]}
        if tool == "list_transactions":
            rows = [
                {
                    "ref": "T1",
                    "merchant": "Amazon",
                    "amount": "-$59.99",
                    "status": "pending",
                    "date": "2026-10-28",
                },
                {
                    "ref": "T2",
                    "merchant": "Costco",
                    "amount": "-$184.32",
                    "status": "posted",
                    "date": "2026-10-26",
                },
                {
                    "ref": "T3",
                    "merchant": "Payroll Deposit",
                    "amount": "$2,450.00",
                    "status": "posted",
                    "date": "2026-10-23",
                },
            ]
            if args["account_ref"] != "A1":
                rows = []
            return {
                "account": self._account(args["account_ref"]),
                "transactions": rows[: args.get("limit", 10)],
            }
        if tool == "list_cards":
            return {
                "cards": [
                    {
                        "ref": "C1",
                        "number": "••••9012",
                        "status": self.card_status,
                        "account_ref": "A1",
                    }
                ]
            }
        if tool == "freeze_card":
            self.card_status = "frozen"
            return {"card": {}, "changed": True, "message": "Card ••••9012 is now frozen."}
        if tool == "open_dispute":
            return {
                "dispute": {},
                "created": True,
                "handoff": args["reason"] == "fraud",
                "message": "Dispute D-11111111 is now open for the $184.32 charge from Costco.",
            }
        if tool == "prepare_transfer":
            cents = int(float(args["amount"]) * 100)
            return {
                "quote_ref": "Q1",
                "summary": f"Move ${cents / 100:,.2f} from chequing ••••4821 to savings ••••7710.",
                "needs_one_time_code": cents > 100_000,
                "expires_in_minutes": 5,
            }
        if tool == "confirm_transfer":
            if args["quote_ref"] not in self.done_quotes:
                self.done_quotes.add(args["quote_ref"])
                self.balances["A1"] -= 20_000
                self.balances["A2"] += 20_000
            return {
                "reference": "T-0000001",
                "created": True,
                "message": "Moved $200.00 from chequing ••••4821 to savings ••••7710.",
                "from_account": self._account("A1"),
                "to_account": self._account("A2"),
            }
        raise AssertionError(f"unexpected tool {tool}")


class FakeJudge:
    """Tier 3 by keywords. `down = True` makes it fail like Ollama being off."""

    RULES: list[tuple[str, Label]] = [
        ("idiot", Label.ABUSE),
        ("can't go on", Label.DISTRESS),
        ("forcing me", Label.DISTRESS),
        ("calling for my", Label.SOCIAL_ENGINEERING),
        ("bitcoin", Label.OFF_TOPIC),
        ("your rules", Label.PROMPT_INJECTION),
    ]

    def __init__(self) -> None:
        self.down = False
        self.calls = 0

    async def judge(self, text: str) -> Label:
        self.calls += 1
        if self.down:
            raise JudgeUnavailable("fake judge is down")
        for keyword, label in self.RULES:
            if keyword in text.lower():
                return label
        return Label.SAFE


class FakeClassifier:
    """Tier 2 that returns a fixed guess."""

    def __init__(self, label: Label = Label.SAFE, score: float = 0.99, threshold: float = 0.8):
        self.guess = Prediction(label, score)
        self.threshold = threshold

    def predict(self, text: str) -> Prediction:
        return self.guess


def fake_moderator(judge: FakeJudge | None = None) -> HybridModerator:
    """Real rules, no classifier (so every turn reaches tier 3), and the fake judge."""
    return HybridModerator(RulesModerator(), classifier=None, judge=judge or FakeJudge())


class FakeEmbedder:
    """A deterministic 'embedding': a bag of character trigrams, so similar text is close."""

    DIMS = 256

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vector = [0.0] * self.DIMS
            cleaned = "".join(ch for ch in text.lower() if ch.isalnum() or ch == " ")
            for i in range(len(cleaned) - 2):
                vector[zlib.crc32(cleaned[i : i + 3].encode()) % self.DIMS] += 1.0
            out.append(vector)
        return out


class FakeChatModel:
    """Answers with a fixed text, so the grounding check can be tested both ways."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls = 0

    async def ainvoke(self, messages: Any) -> Any:
        self.calls += 1
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


class FakeAnswerer:
    """A policy answerer with a canned answer."""

    def __init__(self, text: str = "According to our fee schedule, the NSF fee is $45.00.") -> None:
        from app.policy.answerer import PolicyAnswer

        self.result = PolicyAnswer(text, "POL-001", "rag", 0.8)

    async def answer(self, question: str) -> Any:
        return self.result
