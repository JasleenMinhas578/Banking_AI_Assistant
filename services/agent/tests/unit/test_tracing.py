"""Phase 6: traces keep timings and labels, never words."""

import json
from pathlib import Path

import pytest

from app.tracing import Tracer, safe_summary

pytestmark = pytest.mark.anyio


def test_safe_summary_keeps_labels_and_drops_text() -> None:
    update = {
        "intent": "transfer",
        "reply": "Move $200 from chequing ••••4821 to savings?",
        "messages": [{"role": "caller", "text": "my pin is 2468"}],
        "moderation": {"label": "safe", "tier": "classifier", "score": 0.97, "unsure": False},
        "pending_action": {"tool": "confirm_transfer", "args": {"amount": "200"}},
        "session_token": "secret",
    }

    summary = safe_summary(update)

    assert summary == {
        "intent": "transfer",
        "moderation": {"label": "safe", "tier": "classifier", "score": 0.97, "unsure": False},
        "tool": "confirm_transfer",
    }
    assert "2468" not in json.dumps(summary) and "secret" not in json.dumps(summary)


async def test_a_turn_is_written_as_one_json_line(tmp_path: Path) -> None:
    tracer = Tracer(tmp_path / "calls.jsonl")

    async def route(state: dict) -> dict:
        return {"intent": "balance", "input": "what's my balance"}

    async def respond(state: dict) -> dict:
        return {"reply": "Your chequing has $3,240.50."}

    config = {"configurable": {"thread_id": "c1"}}
    await tracer.wrap("route", route)({}, config)
    await tracer.wrap("respond", respond)({}, config)

    lines = (tmp_path / "calls.jsonl").read_text().splitlines()
    trace = json.loads(lines[0])
    assert [s["node"] for s in trace["spans"]] == ["route", "respond"]
    assert "balance" in json.dumps(trace) and "3,240" not in json.dumps(trace)
