# Shortcuts for everyday commands. Run `make` on its own to see them all.
BANK_API := services/bank_api
MCP := services/mcp_server
AGENT := services/agent

.DEFAULT_GOAL := help
.PHONY: help setup db migrate reset seed dev mcp mcp-token mcp-inspect models chat up down logs test test-unit lint format typecheck

help: ## Show this list
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-12s %s\n", $$1, $$2}'

setup: ## First-time setup: create .env and install Python packages
	@test -f .env || cp .env.example .env
	cd $(BANK_API) && uv sync
	cd $(MCP) && uv sync
	cd $(AGENT) && uv sync

db: ## Start the local Supabase database (if it isn't running already)
	@supabase status >/dev/null 2>&1 || supabase start

migrate: ## Apply new migrations, keeping your data
	supabase migration up

reset: ## Rebuild the database from all migrations, then load the demo data
	supabase db reset
	$(MAKE) seed

seed: ## Load the demo customers (replaces all bank data)
	cd $(BANK_API) && uv run python scripts/seed.py

dev: db ## Run the bank API on your Mac, reloading on every save
	cd $(BANK_API) && uv run uvicorn app.main:app --reload

mcp: ## Run the MCP server on your Mac (needs `make dev` running too)
	cd $(MCP) && uv run python -m app.server

mcp-token: ## Print a verified session token for Priya, for manual MCP testing
	@cd $(MCP) && uv run python scripts/demo_session.py C-1001 2468

mcp-inspect: ## Open MCP Inspector, then connect to http://127.0.0.1:8100/mcp
	npx @modelcontextprotocol/inspector

models: ## Download the Ollama models the agent uses
	ollama pull llama3.2:3b
	ollama pull qwen2.5:7b

chat: ## Talk to the agent in your terminal (needs `make dev`, `make mcp`, Ollama)
	cd $(AGENT) && uv run python -m app.chat

up: db ## Start the database, bank API and MCP server in Docker
	docker compose up --build -d
	@echo "Bank API docs: http://127.0.0.1:8000/docs"
	@echo "MCP server:    http://127.0.0.1:8100/mcp"

down: ## Stop the Docker services and the database
	docker compose down
	supabase stop

logs: ## Follow the Docker services' logs
	docker compose logs -f

test: ## Run every test (live tests skip unless the services are running)
	cd $(BANK_API) && uv run pytest
	cd $(MCP) && uv run pytest
	cd $(AGENT) && uv run pytest

test-unit: ## Run only the fast tests that need no database or server
	cd $(BANK_API) && uv run pytest tests/unit
	cd $(MCP) && uv run pytest tests/unit
	cd $(AGENT) && uv run pytest tests/unit

lint: ## Check code style without changing anything
	cd $(BANK_API) && uv run ruff check . && uv run ruff format --check .
	cd $(MCP) && uv run ruff check . && uv run ruff format --check .
	cd $(AGENT) && uv run ruff check . && uv run ruff format --check .

format: ## Fix code style automatically
	cd $(BANK_API) && uv run ruff check --fix . && uv run ruff format .
	cd $(MCP) && uv run ruff check --fix . && uv run ruff format .
	cd $(AGENT) && uv run ruff check --fix . && uv run ruff format .

typecheck: ## Check type hints with mypy
	cd $(BANK_API) && uv run mypy app
	cd $(MCP) && uv run mypy app
	cd $(AGENT) && uv run mypy app
