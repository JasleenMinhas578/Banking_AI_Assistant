"""`make eval`: the evaluation layers from the design doc, with a Markdown report.

    uv run python -m app.evals          # real models: router, policy answers, conversations
    uv run python -m app.evals --fake   # CI mode: scripted conversations with fake models only

Layers and gates:
  router         intent accuracy on evals/golden/router_utterances.csv        ≥ 90%
  policy         retrieval hit@3, grounded answers with the expected numbers,
                 and every unanswerable question refused                        all refused
  conversations  scripted multi-turn calls: task success, unauthorised writes   ≥ 85%, 0 writes
Safety numbers are checked by code; no model grades another model here.
Writes evals/reports/latest.md.
"""

import argparse
import asyncio
import csv
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import yaml

from app.agent import Agent
from app.config import Settings, settings
from app.graph import build_answerer, build_graph
from app.llm import OllamaRouter
from app.policy.answerer import UNKNOWN, RagAnswerer, numbers_in
from tests.unit.fakes import (
    FakeAnswerer,
    FakeExtractor,
    FakeJudge,
    FakeRouter,
    FakeTools,
    fake_moderator,
)

ROOT = settings.policy_dir.parent.parent
GOLDEN = ROOT / "evals" / "golden"
REPORTS = ROOT / "evals" / "reports"
PIN = {
    "ok": {"verified": True, "customer_code": "C-1001"},
    "wrong": {"verified": False},
    "cancel": {"cancelled": True},
}
CODE = {"ok": {"verified": True}, "wrong": {"verified": False}}


# ---- router ---------------------------------------------------------------------
async def eval_router(config: Settings) -> dict[str, Any]:
    rows = list(csv.DictReader((GOLDEN / "router_utterances.csv").open()))
    router = OllamaRouter(config.router_model, config.ollama_base_url)
    confusion: Counter[tuple[str, str]] = Counter()
    correct = 0
    for row in rows:
        decision = await router.classify([{"role": "caller", "text": row["text"]}])
        confusion[(row["intent"], decision.intent.value)] += 1
        correct += decision.intent.value == row["intent"]
    return {"n": len(rows), "accuracy": correct / len(rows), "confusion": confusion}


# ---- policy answers ----------------------------------------------------------------
async def eval_policy(config: Settings) -> dict[str, Any]:
    golden = yaml.safe_load((GOLDEN / "policy_questions.yaml").read_text())
    answerer = build_answerer(config)
    if not isinstance(answerer, RagAnswerer):
        return {"error": "no policy index; run `make policies`"}
    hits3 = answered = grounded = 0
    sources: Counter[str] = Counter()
    misses = []
    for item in golden["answerable"]:
        vector = (await answerer.embedder.embed([item["q"]]))[0]
        top = answerer.index.search(vector, item["q"], k=3)
        hit = any(h.chunk.policy_id == item["policy"] for h in top)
        hits3 += hit
        answer = await answerer.answer(item["q"])
        sources[answer.source] += 1
        ok = answer.source != "unknown" and all(
            n.replace(",", "") in numbers_in(answer.text) for n in item["numbers"]
        )
        answered += ok
        grounded += answer.grounded
        if not ok or not hit:
            misses.append(
                f"| {item['q']} | {item['policy']} | {'✓' if hit else '✗'} | "
                f"{answer.source} | {answer.text[:80]} |"
            )
    refused = 0
    leaks = []
    for question in golden["unanswerable"]:
        answer = await answerer.answer(question)
        if answer.text == UNKNOWN:
            refused += 1
        else:
            leaks.append(f"| {question} | {answer.source} | {answer.text[:80]} |")
    return {
        "n": len(golden["answerable"]),
        "hit3": hits3 / len(golden["answerable"]),
        "answered": answered / len(golden["answerable"]),
        "sources": sources,
        "unanswerable": len(golden["unanswerable"]),
        "refused": refused / len(golden["unanswerable"]),
        "misses": misses,
        "leaks": leaks,
    }


# ---- conversations --------------------------------------------------------------
async def eval_conversations(config: Settings, fake: bool) -> dict[str, Any]:
    scripts = yaml.safe_load((GOLDEN / "conversations.yaml").read_text())
    passed, unauthorised, failures = 0, 0, []
    for script in scripts:
        tools = FakeTools()
        graph = build_graph(
            config,
            router=FakeRouter() if fake else None,
            extractor=FakeExtractor(**script.get("details", {})),
            toolboxes=tools,
            moderator=fake_moderator(FakeJudge()) if fake else None,
            answerer=FakeAnswerer() if fake else None,
        )
        agent = Agent(
            graph,
            call_id=str(uuid.uuid4()),
            session_token="tok",
            recursion_limit=config.recursion_limit,
        )
        ok, why = True, ""
        for step in script["steps"]:
            if "say" in step:
                output = await agent.say(step["say"])
            elif "pin" in step:
                output = await agent.answer(PIN[step["pin"]])
            elif "code" in step:
                output = await agent.answer(CODE[step["code"]])
            else:
                output = await agent.answer(step["answer"])
            expect = step.get("expect", {})
            if expect.get("kind") and output.kind != expect["kind"]:
                ok, why = False, f"expected {expect['kind']}, got {output.kind}: {output.text[:60]}"
                break
            if expect.get("contains") and expect["contains"] not in output.text:
                ok, why = False, f"missing '{expect['contains']}' in: {output.text[:60]}"
                break
            if expect.get("ended") and not output.ended:
                ok, why = False, "call should have ended"
                break
            if expect.get("handoff") and output.handoff_reason != expect["handoff"]:
                ok, why = False, f"handoff {output.handoff_reason}, expected {expect['handoff']}"
                break
        allowed = set(script.get("writes", []))
        bad_writes = [w for w in tools.writes if w not in allowed]
        if bad_writes:
            unauthorised += len(bad_writes)
            ok, why = False, f"unauthorised write: {bad_writes}"
        passed += ok
        if not ok:
            failures.append(f"| {script['name']} | {why} |")
    return {
        "n": len(scripts),
        "success": passed / len(scripts),
        "unauthorised": unauthorised,
        "failures": failures,
    }


# ---- report ----------------------------------------------------------------------
def gate(ok: bool) -> str:
    return "✅" if ok else "❌"


def report(results: dict[str, Any], fake: bool) -> str:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    mode = "fake models (CI mode)" if fake else "real models on this machine"
    lines = [
        "# Evaluation report",
        f"{stamp} · {mode}",
        "",
        "| Layer | Result | Gate |",
        "|---|---|---|",
    ]
    c = results["conversations"]
    lines.append(
        f"| Conversations ({c['n']} scripted calls) | {c['success']:.0%} task success, "
        f"{c['unauthorised']} unauthorised writes | "
        f"{gate(c['success'] >= 0.85 and c['unauthorised'] == 0)} ≥ 85%, 0 writes |"
    )
    if "router" in results:
        r = results["router"]
        lines.append(
            f"| Router ({r['n']} utterances) | {r['accuracy']:.0%} intent accuracy | "
            f"{gate(r['accuracy'] >= 0.9)} ≥ 90% |"
        )
    if "policy" in results and "error" not in results["policy"]:
        p = results["policy"]
        lines.append(
            f"| Policy retrieval ({p['n']} questions) | {p['hit3']:.0%} right policy in top 3 | "
            f"{gate(p['hit3'] >= 0.9)} ≥ 90% |"
        )
        lines.append(
            f"| Policy answers | {p['answered']:.0%} with the expected numbers; sources "
            f"{dict(p['sources'])} | {gate(p['answered'] >= 0.8)} ≥ 80% |"
        )
        lines.append(
            f"| Unanswerable ({p['unanswerable']}) | {p['refused']:.0%} refused | "
            f"{gate(p['refused'] == 1.0)} all |"
        )
    elif "policy" in results:
        lines.append(f"| Policy | {results['policy']['error']} | ❌ |")
    if c["failures"]:
        lines += [
            "",
            "## Conversation failures",
            "",
            "| Script | Why |",
            "|---|---|",
            *c["failures"],
        ]
    if "router" in results:
        lines += [
            "",
            "## Router confusion (true → predicted, mistakes only)",
            "",
            "| True | Predicted | Count |",
            "|---|---|---|",
        ]
        for (t, p_), n in sorted(results["router"]["confusion"].items()):
            if t != p_:
                lines.append(f"| {t} | {p_} | {n} |")
    if "policy" in results and results["policy"].get("misses"):
        lines += [
            "",
            "## Policy questions not answered as expected",
            "",
            "| Question | Policy | In top 3 | Source | Answer |",
            "|---|---|---|---|---|",
            *results["policy"]["misses"],
        ]
    if "policy" in results and results["policy"].get("leaks"):
        lines += [
            "",
            "## Unanswerable questions that got an answer",
            "",
            "| Question | Source | Answer |",
            "|---|---|---|",
            *results["policy"]["leaks"],
        ]
    return "\n".join(lines) + "\n"


async def run(config: Settings, fake: bool) -> bool:
    results: dict[str, Any] = {"conversations": await eval_conversations(config, fake)}
    if not fake:
        results["router"] = await eval_router(config)
        results["policy"] = await eval_policy(config)
    text = report(results, fake)
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / ("latest-fake.md" if fake else "latest.md")
    out.write_text(text)
    print(text)
    print(f"Saved to {out.relative_to(ROOT)}")
    return "❌" not in text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true", help="fake models: runs anywhere")
    args = parser.parse_args()
    sys.exit(0 if asyncio.run(run(settings, args.fake)) else 1)


if __name__ == "__main__":
    main()
