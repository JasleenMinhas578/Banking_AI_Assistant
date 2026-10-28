"""Agent settings, read from environment variables or the nearest .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    for folder in Path(__file__).resolve().parents:
        if (folder / ".env").is_file():
            return folder / ".env"
    return None


class Settings(BaseSettings):
    """Typed settings. Each field is read from an env var of the same name."""

    model_config = SettingsConfigDict(env_file=_find_env_file(), extra="ignore")

    # Models, served by Ollama running natively on the Mac.
    ollama_base_url: str = "http://127.0.0.1:11434"
    router_model: str = "llama3.2:3b"  # small and fast: runs on every turn
    agent_model: str = "qwen2.5:7b"  # reads details out of the conversation

    # Where the bank's tools live. The agent has no bank or database credentials.
    mcp_url: str = "http://127.0.0.1:8100/mcp"
    # Only used by the chat CLI, which plays the gateway's part (sessions, PIN).
    bank_api_url: str = "http://127.0.0.1:8000"

    # Behaviour, from the design doc
    router_min_confidence: float = 0.7  # below this, ask instead of guessing
    max_clarifications: int = 2  # then hand off to a human
    max_pin_attempts: int = 3  # matches the bank's lock
    history_turns: int = 6  # recent turns kept in state
    recursion_limit: int = 12  # graph steps per turn before handing off
    transactions_to_show: int = 5


settings = Settings()
