# ADR-001: The model chooses words, not permissions

**Status:** accepted · **Date:** 2026-10-20

## Context
A language model can be talked into things. A bank assistant that lets the model decide whether an action is allowed is one clever prompt away from moving money.

## Decision
The model does two jobs only: name the caller's intent, and read details ("savings", "$200") out of the conversation. Every permission is decided by code: the `verified` flag is set only after the bank API accepts the PIN, `confirmed` only after a clear yes, and write tools run only from `ToolNode` after both gates, with the bank API re-checking every rule.

## Consequences
- A jailbreak has nothing to unlock: the worst it can do is choose a wrong intent, which the confirmation step reads back.
- Replies come from templates, so facts are never paraphrased wrong. The cost is less natural wording.
- More code to write and test (the gate tests check every combination), less "magic".
