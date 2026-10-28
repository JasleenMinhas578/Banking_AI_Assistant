"""MCP server settings, read from environment variables or the nearest .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    """Walk up from this file to the first folder holding a .env."""
    for folder in Path(__file__).resolve().parents:
        if (folder / ".env").is_file():
            return folder / ".env"
    return None


class Settings(BaseSettings):
    """Typed settings. Each field is read from an env var of the same name."""

    model_config = SettingsConfigDict(env_file=_find_env_file(), extra="ignore")

    # Where the bank API listens. The MCP server only ever talks to it over HTTP:
    # it has no database credentials at all.
    bank_api_url: str = "http://127.0.0.1:8000"
    bank_timeout_seconds: float = 5.0

    # Where this MCP server listens when run over Streamable HTTP.
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8100

    # How long a prepared transfer can wait for the caller's "yes".
    transfer_quote_minutes: int = 5
    # How long an idle conversation's references (A1, T3...) are kept.
    refs_idle_minutes: int = 30
    # Only a hint for the agent. The bank API enforces the real rule.
    step_up_threshold_cents: int = 100_000

    # Local development only: a session token for stdio clients (MCP Inspector,
    # Claude Desktop), which can't send an Authorization header. Never set in production.
    bank_session_token: str | None = None


settings = Settings()
