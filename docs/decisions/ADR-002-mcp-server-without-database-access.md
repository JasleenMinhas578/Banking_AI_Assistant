# ADR-002: Bank tools through an MCP server with no database access

**Status:** accepted · **Date:** 2026-10-24

## Context
The agent needs to read balances and move money. LangChain tools calling the bank API directly would be simpler and a few milliseconds faster.

## Decision
An MCP server sits between the agent and the bank API. It speaks HTTP to the bank only (a test proves it imports no database driver), returns masked numbers and opaque per-conversation refs (A1, T3, Q1), and splits transfers into `prepare_transfer` (moves nothing) and `confirm_transfer` (one idempotency key per quote).

## Consequences
- The agent holds no bank or database credentials; the trust boundary is a network hop.
- The same tools work in any MCP client (MCP Inspector, Claude Desktop) for demos.
- One more service to run, and a ref registry to keep per conversation.
