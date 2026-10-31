"""Agent settings, read from environment variables or the nearest .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    for folder in Path(__file__).resolve().parents:
        if (folder / ".env").is_file():
            return folder / ".env"
    return None


def _repo_root() -> Path:
    for folder in Path(__file__).resolve().parents:
        if (folder / "data" / "policies").is_dir():
            return folder
    return Path(".")


def _find_model_dir() -> Path:
    """ml/moderation_classifier/model in the repo, wherever the agent is run from."""
    relative = Path("ml") / "moderation_classifier" / "model"
    for folder in Path(__file__).resolve().parents:
        if (folder / "ml" / "moderation_classifier").is_dir():
            return folder / relative
    return relative


class Settings(BaseSettings):
    """Typed settings. Each field is read from an env var of the same name."""

    model_config = SettingsConfigDict(env_file=_find_env_file(), extra="ignore")

    # Models, served by Ollama running natively on the Mac.
    ollama_base_url: str = "http://127.0.0.1:11434"
    router_model: str = "llama3.2:3b"  # small and fast: runs on every turn
    agent_model: str = "qwen2.5:7b"  # reads details out of the conversation
    guard_model: str = "llama-guard3:1b"  # moderation tier 3, with router_model's checklist

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

    # Moderation (phase 4)
    moderation_model_dir: Path = _find_model_dir()  # written by `make moderation-train`
    moderation_threshold: float | None = None  # None: use the one chosen at training time
    max_injection_strikes: int = 3  # attack attempts before handing off
    max_abuse_warnings: int = 1  # warnings before handing off

    # Tracing (phase 6): one masked JSON line per turn; Langfuse too if LANGFUSE_* are set
    trace_path: Path | None = _repo_root() / "traces" / "calls.jsonl"

    # Voice (phase 7), both optional: `uv sync --extra voice` and `make voice-models`
    whisper_model: str = "small"
    voice_model_dir: Path = _repo_root() / "models"

    # Policy answers (phase 5)
    embed_model: str = "nomic-embed-text"
    policy_dir: Path = _repo_root() / "data" / "policies"
    policy_index_path: Path = _repo_root() / "data" / "policies" / "index.json"
    faq_min_similarity: float = 0.90  # at least this close to an approved FAQ: no model
    policy_min_similarity: float = 0.45  # below this, "I don't see that in our policies"


settings = Settings()
