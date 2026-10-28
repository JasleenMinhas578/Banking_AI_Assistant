"""The agent as the gateway sees it: send words in, get a reply or a pause out.

A pause means the graph is waiting for something only the gateway may handle:
  - "pin": collect the PIN securely, verify it with the bank, resume with the outcome
  - "one_time_code": same, for the step-up code
  - "confirm": read the prompt out, resume with the caller's exact words
"""

from dataclasses import dataclass
from typing import Any, Literal

from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.replies import HANDOFF

Kind = Literal["reply", "pin", "one_time_code", "confirm"]


@dataclass(frozen=True)
class AgentOutput:
    kind: Kind
    text: str
    ended: bool = False
    handoff_reason: str | None = None  # why the call went to a human, for logs and demos


class Agent:
    """One phone call. The call_id is the checkpoint thread, so state survives turns."""

    def __init__(
        self,
        graph: CompiledStateGraph,
        *,
        call_id: str,
        session_token: str,
        recursion_limit: int,
    ) -> None:
        self.graph = graph
        self.call_id = call_id
        self.session_token = session_token
        self.recursion_limit = recursion_limit
        self._started = False

    async def say(self, text: str) -> AgentOutput:
        """A new caller turn."""
        update: dict[str, Any] = {"input": text}
        if not self._started:
            update |= {
                "call_id": self.call_id,
                "session_token": self.session_token,
                "verified": False,
                "step_up_verified": False,
                "pin_attempts": 0,
                "clarify_count": 0,
                "tool_failures": 0,
                "step_up_attempts": 0,
                "awaiting": None,
            }
            self._started = True
        return await self._run(update)

    async def answer(self, value: Any) -> AgentOutput:
        """Resume a pause: the PIN/code outcome, or the caller's words at a confirmation."""
        return await self._run(Command(resume=value))

    async def _run(self, payload: Any) -> AgentOutput:
        config: Any = {
            "configurable": {"thread_id": self.call_id},
            "recursion_limit": self.recursion_limit,
        }
        try:
            result = await self.graph.ainvoke(payload, config)
        except GraphRecursionError:
            return AgentOutput(
                "reply", HANDOFF["default"], ended=True, handoff_reason="too_many_steps"
            )

        pauses = result.get("__interrupt__") or []
        if pauses:
            pause = pauses[0].value
            return AgentOutput(pause["kind"], pause["prompt"])
        ended = bool(result.get("ended"))
        summary = result.get("handoff_summary") or {}
        return AgentOutput(
            "reply",
            result.get("reply") or "",
            ended=ended,
            handoff_reason=summary.get("reason") if ended else None,
        )
