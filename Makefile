# Shortcuts for everyday commands. Run `make` on its own to see them all.
BANK_API := services/bank_api
MCP := services/mcp_server
AGENT := services/agent
ML := ml/moderation_classifier

.DEFAULT_GOAL := help
.PHONY: help setup db migrate reset seed dev mcp mcp-token mcp-inspect models chat doctor moderation-train moderation-eval policies eval eval-fake serve voice voice-models up down logs test test-unit lint format typecheck

help: ## Show this list
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-18s %s\n", $$1, $$2}'

setup: ## First-time setup: create .env and install Python packages
	@test -f .env || cp .env.example .env
	cd $(BANK_API) && uv sync
	cd $(MCP) && uv sync
	cd $(AGENT) && uv sync
	cd $(ML) && uv sync

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
	ollama pull llama-guard3:1b
	ollama pull nomic-embed-text

chat: ## Talk to the agent in your terminal (needs `make dev`, `make mcp`, Ollama)
	cd $(AGENT) && uv run python -m app.chat

serve: ## Run the gateway + web app → http://127.0.0.1:8200 (needs `make dev`, `make mcp`, Ollama)
	cd $(AGENT) && uv run uvicorn app.gateway.main:app --port 8200 --reload

voice: ## Install the local speech models' Python packages (Whisper + Kokoro)
	cd $(AGENT) && uv sync --extra voice

voice-models: ## Download the Kokoro voice files (~330 MB) into models/
	mkdir -p models
	curl -L -o models/kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
	curl -L -o models/voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

doctor: ## Check every link the agent needs, one by one
	cd $(AGENT) && uv run python -m app.doctor

moderation-train: ## Build the moderation dataset, train the classifier, write its reports
	cd $(ML) && uv run python generate.py && uv run python train.py && uv run python evaluate.py

policies: ## Index the policy documents and FAQ for policy answers (needs Ollama)
	cd $(AGENT) && uv run python -m app.policy.build

eval: ## Run the evaluation suite with the real models (router, policies, conversations)
	cd $(AGENT) && uv run python -m app.evals

eval-fake: ## Run the scripted-conversation evals with fake models (what CI runs)
	cd $(AGENT) && uv run python -m app.evals --fake

moderation-eval: ## Run all three moderation tiers on the red-team set (needs Ollama)
	cd $(AGENT) && uv run python -m app.moderation_eval

up: db ## Start the database, bank API, MCP server and web app in Docker
	docker compose up --build -d
	@echo "Bank API docs: http://127.0.0.1:8000/docs"
	@echo "MCP server:    http://127.0.0.1:8100/mcp"
	@echo "Web app:       http://127.0.0.1:8200"

down: ## Stop the Docker services and the database
	docker compose down
	supabase stop

logs: ## Follow the Docker services' logs
	docker compose logs -f

test: ## Run every test (live tests skip unless the services are running)
	cd $(BANK_API) && uv run pytest
	cd $(MCP) && uv run pytest
	cd $(AGENT) && uv run pytest
	cd $(ML) && uv run pytest

test-unit: ## Run only the fast tests that need no database or server
	cd $(BANK_API) && uv run pytest tests/unit
	cd $(MCP) && uv run pytest tests/unit
	cd $(AGENT) && uv run pytest tests/unit
	cd $(ML) && uv run pytest

lint: ## Check code style without changing anything
	cd $(BANK_API) && uv run ruff check . && uv run ruff format --check .
	cd $(MCP) && uv run ruff check . && uv run ruff format --check .
	cd $(AGENT) && uv run ruff check . && uv run ruff format --check .
	cd $(ML) && uv run ruff check . && uv run ruff format --check .

format: ## Fix code style automatically
	cd $(BANK_API) && uv run ruff check --fix . && uv run ruff format .
	cd $(MCP) && uv run ruff check --fix . && uv run ruff format .
	cd $(AGENT) && uv run ruff check --fix . && uv run ruff format .
	cd $(ML) && uv run ruff check --fix . && uv run ruff format .

typecheck: ## Check type hints with mypy
	cd $(BANK_API) && uv run mypy app
	cd $(MCP) && uv run mypy app
	cd $(AGENT) && uv run mypy app
