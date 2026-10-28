"""How the agent calls the bank's tools: through the MCP server, never directly.

The caller's session token travels in the Authorization header of the MCP
connection, so no model ever sees it, and the MCP server forwards it to the
bank API, which checks it on every call.
"""

import re
from typing import Any, Protocol

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from app.state import WRITE_TOOLS


class ToolCallError(Exception):
    """A tool refused or failed. code is the bank's (or MCP server's) error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class Toolbox(Protocol):
    async def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]: ...


class ToolboxFactory(Protocol):
    def __call__(self, session_token: str) -> Toolbox: ...


class McpToolbox:
    """Calls tools on the Puffin Bank MCP server for one caller."""

    def __init__(self, mcp_url: str, session_token: str, timeout_seconds: float = 15.0) -> None:
        self.mcp_url = mcp_url
        self._headers = {"Authorization": f"Bearer {session_token}"}
        self._timeout = timeout_seconds

    async def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx2.AsyncClient(
                headers=self._headers, timeout=httpx2.Timeout(self._timeout)
            ) as http:
                transport = streamable_http_client(self.mcp_url, http_client=http)
                async with Client(transport) as client:
                    result = await client.call_tool(tool, args)
        except ToolCallError:
            raise
        except Exception as exc:  # the MCP server is down or unreachable
            raise ToolCallError("tools_unavailable", "The bank's tools aren't answering.") from exc

        if result.is_error:
            raise _error_from(result.content)
        return dict(result.structured_content or {})


def _error_from(content: list[Any]) -> ToolCallError:
    """Turn the MCP error text back into the bank's code and message."""
    text = " ".join(block.text for block in content if isinstance(block, TextContent))
    return parse_tool_error(text)


_ERROR = re.compile(r"^(?:Error executing tool \S+: )?([a-z_]+): (.+)$", re.DOTALL)


def parse_tool_error(text: str) -> ToolCallError:
    """'Error executing tool freeze_card: unknown_reference: ...' -> code + message."""
    match = _ERROR.match(text.strip())
    if match:
        return ToolCallError(match.group(1), match.group(2).strip())
    return ToolCallError("tool_error", text.strip() or "The tool failed.")


class ReadOnlyToolbox:
    """Wraps a toolbox so only read-only tools can be called.

    The planner gets this one: it can look things up, but it physically
    cannot freeze a card, open a dispute or move money.
    """

    def __init__(self, inner: Toolbox) -> None:
        self.inner = inner

    async def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool in WRITE_TOOLS:
            raise PermissionError(f"{tool} changes data and may only run after confirmation")
        return await self.inner.call(tool, args)
