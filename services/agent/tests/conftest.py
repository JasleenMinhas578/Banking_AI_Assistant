"""Shared pytest setup: async tests run on asyncio through anyio's plugin."""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
