# ADR-004: Moderation as a three-tier cascade

**Status:** accepted · **Date:** 2026-10-29

## Context
Every caller turn must be screened for secrets said aloud, prompt injection, social engineering, abuse and distress, within a 2-second voice budget. An LLM on every turn costs about 500 ms; rules alone are brittle.

## Decision
Rules (regex + Luhn, ~1 ms) → a TF-IDF + logistic-regression classifier (~1.5 ms) that decides only above a threshold chosen by cross-validation grouped by template → Llama Guard 3 1B and a 3B bank checklist in parallel, only when the classifier is unsure. If tier 3 is down, general questions still work but account requests go to a person.

## Consequences
- Most turns are decided in milliseconds; the slow tier runs on about 40% today, which more varied training data will reduce.
- Three components to maintain and a threshold to tune; the reports in `ml/moderation_classifier/reports` document the tuning.
- Grouped cross-validation gave 83.1% accuracy where a random split gave 99.9%: the honest number is the one we ship.
