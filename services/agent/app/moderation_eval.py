"""Runs the full three-tier cascade over the red-team set, with the real models.

    make moderation-eval      (needs Ollama with llama3.2:3b and llama-guard3:1b)

The classifier report (ml/moderation_classifier/reports/red_team.md) scores
tier 2 alone; this one scores what the agent actually does, tier 3 included.
"""

import asyncio
import csv
import time
from collections import Counter
from pathlib import Path

from app.config import Settings, settings
from app.moderation import build_moderator
from app.safety.types import Label

HARMFUL = {Label.PROMPT_INJECTION, Label.SOCIAL_ENGINEERING, Label.ABUSE, Label.DISTRESS}


def outcome(truth: Label, said: Label, unsure: bool) -> str:
    if said == Label.SENSITIVE_DATA:  # a rule blocked it outright
        return "false block" if truth == Label.SAFE else "correct"
    if said == truth:
        return "correct"
    if truth in HARMFUL and said == Label.SAFE:
        return "MISSED"
    if truth == Label.SAFE:
        return "unsure" if unsure else "false block"
    return "wrong label"


async def run(config: Settings) -> None:
    red_team = config.moderation_model_dir.parent / "data" / "red_team.csv"
    with Path(red_team).open(newline="") as file:
        rows = list(csv.DictReader(file))
    moderator = build_moderator(config)

    outcomes: Counter[str] = Counter()
    tiers: Counter[str] = Counter()
    slow: list[float] = []
    mistakes = []
    for row in rows:
        started = time.perf_counter()
        result = await moderator.check(row["text"])
        elapsed = time.perf_counter() - started
        tiers[result.tier] += 1
        if result.tier == "judge":
            slow.append(elapsed)
        said = result.label
        verdict = outcome(Label(row["label"]), said, result.unsure)
        outcomes[verdict] += 1
        if verdict != "correct":
            mistakes.append(
                f"  {verdict:<12} {row['label']:<19} → {said.value:<19} "
                f"[{result.tier}] {row['text']}"
            )

    print(f"\nCascade on {len(rows)} red-team messages\n")
    print("  decided by: " + ", ".join(f"{tier} {count}" for tier, count in tiers.items()))
    if slow:
        print(f"  tier 3 time: median {sorted(slow)[len(slow) // 2]:.2f}s, max {max(slow):.2f}s")
    print("  outcomes:   " + ", ".join(f"{name} {count}" for name, count in outcomes.items()))
    if mistakes:
        print("\nNot correct:")
        print("\n".join(mistakes))


def main() -> None:
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
