# Puffin Bank Voice Assistant

A voice banking assistant for a fictional bank, built end to end with local, free tools: LangGraph, FastAPI, MCP, Supabase and Ollama models running on one MacBook. Callers check balances, freeze a lost card, dispute a charge or move money between their own accounts, by voice or text.

The hard part of an AI agent at a bank isn't the conversation. It's making sure the model can never move money it shouldn't. This project is built around one rule: **the model chooses words, not permissions.** The agent can only *ask* for an action; a separate bank API checks every rule again and has the final say.

> **Status:** phase 1 of 8 is done: the bank API, its database, and about 150 tests. The AI layers come next (see [Roadmap](#roadmap)).

## Architecture

![Architecture: web app, gateway, LangGraph agent, MCP server, bank API and Supabase, with Ollama and Langfuse beside the agent](docs/diagrams/architecture.png)

| Component | What it does | Built with |
| --- | --- | --- |
| Web app | Pick a demo customer, then talk or type | React + Vite |
| Gateway | Sessions, speech to text and back | FastAPI, Whisper, Kokoro |
| Agent | Moderation, intent routing, identity gate, confirmation, tool calls | LangGraph + LangChain |
| MCP server | Exposes the bank's actions as tools, with masked results | Official MCP Python SDK |
| **Bank API** | **The final say on every rule: PIN, limits, ownership, audit** | **FastAPI** |
| **Database** | Bank data, plus policy documents for RAG | **Supabase (Postgres + pgvector)** |
| Models | Main agent, router, safety classifier, embeddings | Ollama (Qwen 2.5 7B / Llama 3.1 8B, Llama 3.2 3B, Llama Guard 3 1B, nomic-embed-text) |
| Tracing | One trace per call, with PINs and card numbers redacted | Langfuse (self-hosted) |

## Quick start

**You need:** Docker Desktop, the [Supabase CLI](https://supabase.com/docs/guides/cli), [uv](https://docs.astral.sh/uv/), and `make` (built into macOS).

```bash
make setup   # creates .env and installs Python packages
make db      # starts the local Supabase database (the first start creates the tables)
make seed    # loads the demo customers
make dev     # runs the bank API at http://127.0.0.1:8000/docs
```

To run the API in Docker instead of on your Mac, use `make up` (and `make down` to stop everything). After pulling new migrations, `make migrate` applies them without wiping data. Run `make` on its own to see every command.

### Demo customers

All data is fictional. Picking a profile does **not** verify you: you still enter the PIN.

| Customer | Code | PIN | Their story |
| --- | --- | --- | --- |
| Priya Sharma | C-1001 | 2468 | Everyday customer, healthy balances |
| Marcus Lee | C-1002 | 1357 | Lost his card and wants it frozen |
| Elena Rossi | C-1003 | 8642 | Spotted a suspicious charge to dispute |
| Sam Okafor | C-1004 | 9753 | Low balance, keeps hitting limits |
| The impostor | – | – | No PIN; tries injection and impersonation |

### Try it in the browser

Open `http://127.0.0.1:8000/docs`, then:

1. `POST /sessions` and copy the `session_token`. Click **Authorize** and paste it.
2. `POST /sessions/verify` with `C-1001` and PIN `2468`.
3. `GET /accounts`, then `POST /transfers` to move $200 (`"amount_cents": 20000`) from chequing to savings. Put any unique text in the `Idempotency-Key` header.

## Bank API (phase 1)

| Endpoint | What it does |
| --- | --- |
| `GET /health` | 200 if the database answers, 503 if not |
| `POST /sessions` | Starts a call. The session is not verified yet |
| `POST /sessions/verify` | Checks customer code and PIN |
| `GET /sessions/me` | Whether the session is verified, and when it times out |
| `POST /sessions/step-up` · `/step-up/verify` | One-time code for transfers over $1,000 |
| `GET /accounts` | The caller's accounts, masked, with balances |
| `GET /accounts/{id}/transactions` | Recent activity on one of the caller's accounts |
| `GET /cards` · `POST /cards/{id}/freeze` | List cards; freeze one (there is no unfreeze) |
| `GET /disputes` · `POST /disputes` | List or open disputes on purchases |
| `POST /transfers` | Move money between the caller's own accounts |

### Rules the API enforces

Every number below lives in [`config.py`](services/bank_api/app/core/config.py) and matches the policy documents.

| Rule | How it's enforced |
| --- | --- |
| 3 wrong PINs lock the account | One atomic `UPDATE` counts and locks, so parallel guesses can't slip through |
| Sessions expire after 10 idle minutes | Checked on every request; activity pushes the timeout back |
| You only ever see your own data | The customer comes from the session, never the request. Ownership is in the SQL `WHERE` clause |
| Someone else's account looks like it doesn't exist | 404, not 403, so account IDs can't be probed |
| Cards freeze instantly, and only a human can unfreeze | There is no unfreeze code anywhere |
| Disputes within 60 days, one per purchase, not while pending | `ON CONFLICT DO NOTHING` on a unique column: the database decides |
| Transfers: own accounts, ≤ $2,500 each, ≤ $5,000 a day, never below $0 | Checks run before any money moves; the database also rejects negative balances |
| Over $1,000 needs a one-time code | 6 digits, bcrypt-hashed, 5 minutes, 3 tries |
| A retried transfer never moves money twice | `Idempotency-Key` header; a repeat returns the first result |
| Two transfers at once can't both overdraw | The customer's row is locked, so their transfers run one at a time |
| A crash mid-transfer moves nothing | Every request is one database transaction; refusals are saved, crashes roll back |
| PINs and codes never leak | Stored only as bcrypt hashes, hidden in logs, never echoed in errors |
| Everything is on record | An `audit_log` row for every action, allowed or denied |

## Tests

```bash
make test        # everything (database tests reseed the demo data)
make test-unit   # fast tests with no database
make lint        # code style
```

- **Unit tests** check each business rule with fake, in-memory repositories, including exact edges like "60 days is allowed, 60 days and a minute is not".
- **Integration tests** go through real HTTP and the real database. They cover the sad paths as well: wrong customers, expired sessions, malformed input, two requests racing, and a simulated crash halfway through a transfer.

## Project layout

```text
puffin-bank-assistant/
├── Makefile, docker-compose.yml, .env.example
├── data/seed/profiles.yaml          # the demo customers
├── docs/diagrams/                   # architecture and flow diagrams
├── supabase/migrations/             # database schema, one file per change
└── services/bank_api/
    ├── app/
    │   ├── api/routes/              # HTTP in, HTTP out, no logic
    │   ├── api/deps.py              # wires repositories into services
    │   ├── services/                # business rules
    │   ├── repositories/            # the only place with SQL
    │   ├── models/                  # database rows as Python objects
    │   ├── schemas/                 # what the outside world sends and sees
    │   └── core/                    # settings, database, errors, security
    ├── scripts/seed.py
    └── tests/{unit,integration}/
```

Each layer only talks to the one below it: route → service → repository → database.

## Roadmap

| Phase | What | Status |
| --- | --- | --- |
| 1 | Bank API, database, seed data, tests | ✅ Done |
| 2 | MCP server exposing the bank's actions as tools | Next |
| 3 | Text agent in LangGraph: router, identity gate, confirmation, tools | |
| 4 | Hybrid moderation: rules → scikit-learn classifier → Llama Guard | |
| 5 | RAG over the policy documents, with a grounding check | |
| 6 | Evaluations and tracing: Ragas, golden conversations, red team, model benchmark | |
| 7 | Voice: Whisper, Kokoro, streaming, barge-in | |
| 8 | Polish: web app, decision records, demo video | |
