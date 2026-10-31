# ADR-005: The policy index is a file, not a vector database

**Status:** accepted · **Date:** 2026-10-31

## Context
The design planned pgvector in Supabase for policy chunks. There are five policies, about 40 chunks of 768 numbers each, and the agent is meant to hold no database credentials.

## Decision
`make policies` embeds the chunks and the approved FAQ with nomic-embed-text and writes `data/policies/index.json`. Search is hybrid in-process: cosine similarity plus BM25, merged with reciprocal rank fusion. An FAQ hit at 90% similarity answers with no model; otherwise the 7B model answers from the top 3 chunks and a grounding check rejects any number not in them.

## Consequences
- Nothing new to run, and the agent keeps zero database access.
- Fine to a few thousand chunks; a real bank with hundreds of documents would move the same index into pgvector behind the same `PolicyIndex` interface.
- Re-indexing is a command, not a background job; only changed files are re-embedded.
