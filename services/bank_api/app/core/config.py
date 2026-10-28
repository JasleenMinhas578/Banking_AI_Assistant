"""App settings loaded from the root .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Typed settings. Each field is read from an env var of the same name."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str

    # Business rules. Defaults match the design doc; override in .env if needed.
    max_pin_attempts: int = 3
    session_idle_minutes: int = 10


settings = Settings()
