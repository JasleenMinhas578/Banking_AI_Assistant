"""Execute tool: the only place a bank tool that changes data is ever called.

It re-checks the gates itself (defence in depth), calls the tool through the
MCP server, and retries once only when the tools didn't answer at all.
"""

from typing import Any

from app.nodes.planner_node import refusal
from app.routing import gate_allows
from app.state import ConversationState
from app.toolbox import ToolboxFactory, ToolCallError

RETRYABLE = frozenset({"tools_unavailable", "bank_unavailable"})
DONE = {"pending_action": None, "confirmed": False}


class ToolNode:
    def __init__(self, toolboxes: ToolboxFactory) -> None:
        self.toolboxes = toolboxes

    async def run(self, state: ConversationState) -> dict[str, Any]:
        action = state.get("pending_action")
        if not action:
            return {"reply": "There's nothing waiting to be done."}
        if not gate_allows(state, dict(action)):
            # Should be impossible: routing never gets here without the gates.
            return {**DONE, "handoff_reason": "gate_violation"}

        toolbox = self.toolboxes(state["session_token"])
        for attempt in (1, 2):
            try:
                data = await toolbox.call(action["tool"], action.get("args", {}))
                return {**DONE, "tool_result": {"tool": action["tool"], "data": data}}
            except ToolCallError as error:
                if error.code in RETRYABLE and attempt == 1:
                    continue  # safe: every write tool is idempotent
                failures = state.get("tool_failures", 0) + 1
                return {**DONE, "tool_failures": failures, **refusal(error)}
        return {**DONE, "handoff_reason": "tools_unavailable"}
