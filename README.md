# Puffin Bank Voice Assistant

A voice banking assistant for a fictional bank, built with **LangGraph, FastAPI, MCP, Supabase and local Ollama models**. It's 100% free and runs on one MacBook.

> **The model chooses words, not permissions.** The agent can only *ask* for an action. The bank API re-checks every rule and has the final say.

**Status:** phases 1–3 of 8 done (bank API, MCP server, LangGraph agent). [Roadmap](#roadmap)

## Architecture

![Architecture](docs/diagrams/architecture.png)

| Component | Role | Tech | Status |
| --- | --- | --- | --- |
| Web app | Pick a demo customer, talk or type | React + Vite | Phase 8 |
| Gateway | Sessions, speech in/out | FastAPI, Whisper, Kokoro | Phase 7 |
| Agent | Moderation → routing → identity → confirm → tools | LangGraph | ✅ Built (ML moderation, RAG next) |
| MCP server | Bank actions as tools, masked results | MCP Python SDK | ✅ Built |
| Bank API | Final say: PIN, limits, ownership, audit | FastAPI | ✅ Built |
| Database | Bank data + policy vectors | Supabase (Postgres, pgvector) | ✅ Built |
| Models | Router 3B, agent 7B (safety, embeddings later) | Ollama | ✅ Built |
| Tracing | One trace per call, secrets redacted | Langfuse | Phase 6 |

## How a request flows

```mermaid
flowchart LR
    caller(["Caller:<br/>“Move $200<br/>to savings”"])

    subgraph ai["AI side · holds no bank credentials"]
        direction TB
        mod["1 · Moderation<br/>blocks attacks"]
        route["2 · Router<br/>intent + risk tier"]
        verified{"3 · PIN<br/>verified?"}
        pin["Keypad PIN entry<br/>the model never sees it"]
        plan["4 · prepare_transfer<br/>summary only,<br/>nothing moves"]
        ok{"5 · Caller<br/>says yes?"}
        stop(["Cancelled,<br/>nothing moves"])
        mod --> route --> verified
        verified -- no --> pin --> verified
        verified -- yes --> plan --> ok
        ok -- no --> stop
    end

    mcp["6 · MCP server<br/>confirm_transfer"]

    subgraph bank["Bank side · has the final say"]
        direction TB
        api{"7 · Bank API checks<br/>session · ownership<br/>limits · one-time code<br/>· balance"}
        refuse(["Refused<br/>+ audit log"])
        move[("Money moves<br/>+ audit log<br/>all or nothing")]
        api -- a rule fails --> refuse
        api -- all pass --> move
    end

    reply(["Reply:<br/>“Done. Reference T-…”"])

    caller --> mod
    ok -- yes --> mcp --> api
    refuse --> reply
    move --> reply

    classDef step fill:#ffffff,stroke:#8b5cf6,color:#1f2937
    classDef good fill:#ecfdf5,stroke:#10b981,color:#065f46
    classDef bad fill:#fef2f2,stroke:#ef4444,color:#991b1b
    classDef ends fill:#eef2ff,stroke:#6366f1,color:#1f2937
    class mod,route,pin,plan,verified,ok step
    class api,move,mcp good
    class refuse,stop bad
    class caller,reply ends
    style ai fill:#faf5ff,stroke:#c4b5fd,stroke-dasharray:6 4,color:#6d28d9
    style bank fill:#f0fdf4,stroke:#86efac,stroke-dasharray:6 4,color:#15803d
```

## Quick start

Needs Docker Desktop, [Supabase CLI](https://supabase.com/docs/guides/cli), [uv](https://docs.astral.sh/uv/).

```bash
make setup    # .env + Python packages
make db       # local Supabase (first start creates the tables)
make seed     # demo customers
make dev      # bank API  → http://127.0.0.1:8000/docs
make mcp      # MCP server → http://127.0.0.1:8100/mcp   (second terminal)
make models   # Ollama models for the agent (once)
make chat     # talk to the agent                       (third terminal)
make test     # all tests
```

`make up` runs everything in Docker. `make` alone lists every command.

| Demo customer | Code | PIN | Story |
| --- | --- | --- | --- |
| Priya Sharma | C-1001 | 2468 | Healthy balances |
| Marcus Lee | C-1002 | 1357 | Lost card → freeze |
| Elena Rossi | C-1003 | 8642 | Suspicious charge → dispute |
| Sam Okafor | C-1004 | 9753 | Low balance → hits limits |
| Impostor | – | – | Tries injection and impersonation |

## What the bank enforces

| Rule | How |
| --- | --- |
| 3 wrong PINs → locked | One atomic `UPDATE`; parallel guesses can't slip through |
| 10 idle minutes → session expires | Checked on every request |
| Only your own data | Customer comes from the session; ownership in the SQL `WHERE` |
| Other people's IDs look nonexistent | `404`, never `403` |
| Freeze instantly, unfreeze human-only | No unfreeze code exists |
| Disputes: ≤ 60 days, posted, one per purchase | Unique column + `ON CONFLICT DO NOTHING` |
| Transfers: own accounts, ≤ $2,500, ≤ $5,000/day, ≥ $0 | Checked before money moves; DB rejects negative balances |
| Over $1,000 → one-time code | 6 digits, hashed, 5 min, 3 tries |
| Retries never pay twice | `Idempotency-Key` |
| No race conditions | Customer row locked per transfer |
| Crash mid-transfer → nothing moves | One DB transaction per request |
| Secrets never leak | bcrypt hashes; never logged or echoed |
| Everything audited | `audit_log` row per action, allowed or denied |

All limits live in [`config.py`](services/bank_api/app/core/config.py).

## The agent

The LLM only **classifies the intent** and **reads details** ("savings", "$200"). Code decides everything else.

```mermaid
flowchart TD
    input(["Caller's words"]) --> moderate["1 · Moderate<br/>rules · phase 4 adds ML"]
    moderate -- blocked --> respond
    moderate -- passed --> route["2 · Route<br/>3B model: intent + confidence<br/>code: risk tier"]
    route -- "unsure · policy · small talk" --> simple["Clarify or answer<br/>no bank tools"]
    route -- banking --> verify{{"3 · Verify identity<br/>pause: PIN on keypad<br/>(skipped once verified)"}}
    verify -- correct --> plan["4 · Plan<br/>7B model reads the details<br/>read-only tools only"]
    plan -- "read only<br/>(balance, transactions)" --> execute
    plan -- "changes data<br/>(freeze, dispute, transfer)" --> confirm{{"6 · Confirm<br/>pause: clear yes?"}}
    plan -- "transfer over $1,000" --> stepup{{"5 · Step-up<br/>pause: one-time code"}}
    stepup --> confirm
    confirm -- yes --> execute["7 · Execute<br/>re-checks the gates<br/>calls the MCP tool"]
    confirm -- "anything else" --> respond
    plan -- "detail missing" --> respond
    simple --> respond["8 · Respond<br/>fixed templates"]
    execute --> respond
    respond --> reply(["Reply"])

    route -. "wants a person" .-> handoff["Hand off<br/>masked summary"]
    verify -. "3 wrong PINs" .-> handoff
    execute -. "tools fail twice" .-> handoff
    handoff --> reply

    classDef model fill:#f5f3ff,stroke:#8b5cf6,color:#1f2937
    classDef pause fill:#fffbeb,stroke:#f59e0b,color:#78350f
    classDef bank fill:#ecfdf5,stroke:#10b981,color:#065f46
    classDef stop fill:#fef2f2,stroke:#ef4444,color:#991b1b
    classDef plain fill:#ffffff,stroke:#9ca3af,color:#1f2937
    classDef ends fill:#eef2ff,stroke:#6366f1,color:#1f2937
    class route,plan model
    class verify,stepup,confirm pause
    class execute bank
    class handoff stop
    class moderate,simple,respond plain
    class input,reply ends
```

| Safeguard | How |
| --- | --- |
| PIN and codes never reach a model | The graph pauses (`interrupt`); the gateway sends them straight to the bank |
| Nothing changes without a clear yes | Only "yes", "go ahead"… count; "yes, and also…" cancels |
| Planner can't change anything | It gets a read-only toolbox; writes run only in Execute |
| Gates checked twice | Routing, then again inside Execute |
| No stale yes | Pending actions are cleared at the end of every turn |
| Injection, card numbers, PINs in text | Blocked before any model; history keeps `[withheld]` |
| Facts aren't paraphrased | Replies come from fixed templates |
| Unsure or stuck | Clarify twice, then hand off with a masked summary |

## MCP tools

| Tool | Does | Writes? |
| --- | --- | --- |
| `get_accounts` | Accounts → refs `A1`, `A2`… | – |
| `list_transactions` | Activity → refs `T1`, `T2`… | – |
| `list_cards` | Cards → refs `C1`… | – |
| `list_disputes` | Disputes and status | – |
| `freeze_card` | Freeze (idempotent) | ✏️ |
| `open_dispute` | Dispute, or return the open one | ✏️ |
| `prepare_transfer` | Step 1: summary, moves nothing | – |
| `confirm_transfer` | Step 2: moves money, once | 💸 |

- **No real IDs, tokens or PINs** reach the model: only short per-conversation refs.
- **No database access:** HTTP to the bank API only, [enforced by a test](services/mcp_server/tests/unit/test_no_database_access.py).
- **Try it:** `make mcp-token` → `make mcp-inspect` → Streamable HTTP, `http://127.0.0.1:8100/mcp`, header `Authorization: Bearer <token>`.

## Tests

| Suite | Covers | Command |
| --- | --- | --- |
| Bank unit | Every rule at its exact edges, fake repositories | `make test-unit` |
| Bank integration | Real HTTP + DB: sad paths, races, mid-transfer crash | `make test` |
| MCP unit | Tools, refs, masking, two-step transfer, MCP protocol | `make test-unit` |
| MCP live | MCP → bank API → DB, end to end | `make test` (with `make dev`) |
| Agent unit | Routing table, every gate combination, each node, whole conversations | `make test-unit` |
| Agent live | Real Ollama models → MCP → bank | `make test` (all services up) |

## Project layout

```text
services/
├── bank_api/     route → service → repository → database
├── mcp_server/   server.py (MCP) → tools.py (logic) → bank_client.py (HTTP)
├── agent/        graph.py (LangGraph) → nodes/ (one per step) → routing.py (rules)
supabase/migrations/   schema, one file per change
data/seed/             demo customers
docs/diagrams/         architecture + flows
```

## Roadmap

| # | Phase | Status |
| --- | --- | --- |
| 1 | Bank API, database, tests | ✅ |
| 2 | MCP server | ✅ |
| 3 | LangGraph text agent: router, identity gate, confirmation, tools | ✅ |
| 4 | Moderation: rules → scikit-learn → Llama Guard | 🔨 Next |
| 5 | RAG over policies, grounding check | |
| 6 | Evals + tracing: Ragas, red team, model benchmark | |
| 7 | Voice: Whisper, Kokoro, streaming | |
| 8 | Web app, decision records, demo video | |
