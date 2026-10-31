# ADR-003: Everything local and free

**Status:** accepted · **Date:** 2026-10-20

## Context
The project must be something anyone can clone and run, and a portfolio demo should not depend on API keys or a monthly bill.

## Decision
Ollama serves every model (llama3.2:3b routes, qwen2.5:7b reads details and answers policy questions, llama-guard3:1b judges, nomic-embed-text embeds). Supabase CLI runs Postgres locally. Speech uses Whisper and Kokoro on the CPU. scikit-learn trains the moderation classifier in seconds.

## Consequences
- Smaller models than a hosted API, so more checks live in code (account-name safety net, grounding check, templates).
- No data leaves the laptop, which is the right default for a bank.
- Model pulls are a few GB and the first call of each model is slow; `make doctor` checks every link.
