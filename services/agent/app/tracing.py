"""One trace per call, one span per graph node. Masked first, words never.

Every span records the node's name, how long it took, and only the fields that
are safe to keep: intent, risk tier, which moderation tier decided, the policy
source, the tool name, the handoff reason. Caller text, PINs, tokens and
amounts never enter a trace. Traces go to traces/calls.jsonl, and to Langfuse
as well when LANGFUSE_PUBLIC_KEY is set and the package is installed.
"""

import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SAFE_KEYS = (
    "intent",
    "risk_tier",
    "router_confidence",
    "handoff_reason",
    "ended",
    "verified",
    "confirmed",
    "step_up_verified",
)


def safe_summary(update: dict[str, Any] | None) -> dict[str, Any]:
    """The part of a node's update that may be kept."""
    if not update:
        return {}
    out: dict[str, Any] = {k: update[k] for k in SAFE_KEYS if k in update}
    if "moderation" in update:
        m = update["moderation"]
        out["moderation"] = {k: m.get(k) for k in ("label", "tier", "score", "unsure")}
    if "policy" in update:
        out["policy"] = update["policy"]
    if update.get("pending_action"):
        out["tool"] = update["pending_action"].get("tool")
    if update.get("tool_result"):
        out["tool_result"] = update["tool_result"].get("tool")
    return out


@dataclass
class Span:
    node: str
    started_at: str
    ms: float
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class CallTrace:
    call_id: str
    spans: list[Span] = field(default_factory=list)


class Tracer:
    """Collects spans per call and writes each finished turn as one JSON line."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._calls: dict[str, CallTrace] = {}
        self.last_turn: dict[str, dict[str, Any]] = {}  # per call, for the demo UI
        self._langfuse = _langfuse_client()

    def wrap(self, name: str, run: Callable[[Any], Awaitable[dict[str, Any]]]) -> Callable:
        async def traced(state: Any, config: Any = None) -> dict[str, Any]:
            # The thread id LangGraph runs under is the call id (see Agent._run).
            configured = (config or {}).get("configurable", {}).get("thread_id")
            call_id = str(configured or state.get("call_id") or "unknown")
            started = time.perf_counter()
            stamp = datetime.now(UTC).isoformat(timespec="milliseconds")
            try:
                update = await run(state)
            except Exception as exc:
                self._record(call_id, Span(name, stamp, _ms(started), error=type(exc).__name__))
                raise
            self._record(call_id, Span(name, stamp, _ms(started), safe_summary(update)))
            if name in ("respond", "handoff"):
                self.flush(call_id)
            return update

        return traced

    def _record(self, call_id: str, span: Span) -> None:
        self._calls.setdefault(call_id, CallTrace(call_id)).spans.append(span)

    def flush(self, call_id: str) -> None:
        trace = self._calls.pop(call_id, None)
        if not trace:
            return
        line = {
            "call_id": call_id,
            "turn_ms": round(sum(s.ms for s in trace.spans), 1),
            "spans": [asdict(s) for s in trace.spans],
        }
        if self.path:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a") as file:
                    file.write(json.dumps(line) + "\n")
            except OSError as exc:
                log.warning("Could not write trace: %s", exc)
        if self._langfuse:
            _send_to_langfuse(self._langfuse, line)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _langfuse_client() -> Any | None:
    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        return None
    try:
        from langfuse import Langfuse  # optional dependency

        return Langfuse()
    except Exception as exc:  # not installed or misconfigured
        log.warning("Langfuse not available: %s", exc)
        return None


def _send_to_langfuse(client: Any, line: dict[str, Any]) -> None:
    try:
        trace = client.trace(id=line["call_id"], name="call", metadata={"turn_ms": line["turn_ms"]})
        for span in line["spans"]:
            trace.span(name=span["node"], metadata=span["summary"] | {"ms": span["ms"]})
    except Exception as exc:
        log.warning("Langfuse export failed: %s", exc)
