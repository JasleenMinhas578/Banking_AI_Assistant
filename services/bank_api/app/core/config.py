"""App settings, read from environment variables or the nearest .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    """Walk up from this file to the first folder holding a .env.

    On your Mac that's the repo root. Inside Docker there is none, and
    settings come from the container's environment variables instead.
    """
    for folder in Path(__file__).resolve().parents:
        if (folder / ".env").is_file():
            return folder / ".env"
    return None


class Settings(BaseSettings):
    """Typed settings. Each field is read from an env var of the same name."""

    model_config = SettingsConfigDict(env_file=_find_env_file(), extra="ignore")

    database_url: str

    # Business rules. Defaults match the design doc; override in .env if needed.
    # Sessions and PINs
    max_pin_attempts: int = 3
    session_idle_minutes: int = 10

    # Transactions and disputes (POL-003)
    transactions_default_limit: int = 20
    transactions_max_limit: int = 100
    dispute_window_days: int = 60

    # Transfers (POL-004). Money is always in cents.
    per_transfer_limit_cents: int = 250_000  # $2,500
    daily_transfer_limit_cents: int = 500_000  # $5,000
    step_up_threshold_cents: int = 100_000  # over $1,000 needs a one-time code
    bank_timezone: str = "America/St_Johns"  # "per calendar day, Newfoundland time"

    # One-time codes for step-up verification
    otp_ttl_minutes: int = 5
    otp_max_attempts: int = 3
    # There's no SMS in a demo, so the API returns the code in its response.
    # Never turn this on for real customers.
    otp_demo_mode: bool = True


settings = Settings()
