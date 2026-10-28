"""The current time. Passed into classes as a parameter so tests can control it."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """The current time in UTC."""
    return datetime.now(UTC)
