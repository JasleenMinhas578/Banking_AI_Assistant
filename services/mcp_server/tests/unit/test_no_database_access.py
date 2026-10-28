"""Guard rails: the MCP server must never be able to reach the database directly.

It may only talk to the bank API over HTTP. These tests fail the build if a
database driver, a database setting, or a database import ever sneaks in.
"""

import ast
import tomllib
from pathlib import Path

import pytest

from app.config import Settings

SERVICE = Path(__file__).resolve().parents[2]
FORBIDDEN = {
    "psycopg",
    "psycopg2",
    "psycopg-binary",
    "psycopg2-binary",
    "asyncpg",
    "pg8000",
    "sqlalchemy",
    "sqlmodel",
    "supabase",
    "postgrest",
    "databases",
    "peewee",
    "tortoise-orm",
}


def _name(requirement: str) -> str:
    """'psycopg[binary]>=3.3' -> 'psycopg'."""
    for stop in "[<>=!~; ":
        requirement = requirement.split(stop)[0]
    return requirement.strip().lower().replace("_", "-")


def test_no_database_driver_in_direct_dependencies() -> None:
    project = tomllib.loads((SERVICE / "pyproject.toml").read_text())["project"]

    names = {_name(dep) for dep in project["dependencies"]}

    assert not names & FORBIDDEN


def test_no_database_driver_anywhere_in_the_lock_file() -> None:
    """Catches drivers pulled in indirectly by another package, too."""
    lock_file = SERVICE / "uv.lock"
    if not lock_file.exists():
        pytest.skip("No uv.lock yet: run `uv sync` first.")

    packages = {p["name"].lower() for p in tomllib.loads(lock_file.read_text())["package"]}

    assert not packages & FORBIDDEN


def test_no_database_setting() -> None:
    fields = {name.lower() for name in Settings.model_fields}

    assert not any(word in field for field in fields for word in ("database", "postgres", "db_"))


def test_no_database_imports_in_the_code() -> None:
    imported: set[str] = set()
    for source in (SERVICE / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

    assert not {name.replace("_", "-") for name in imported} & FORBIDDEN
