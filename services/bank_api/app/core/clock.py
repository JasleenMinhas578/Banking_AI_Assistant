"""The current time. Services take a clock as a parameter so tests can control it."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """The current time in UTC."""
    return datetime.now(UTC)
