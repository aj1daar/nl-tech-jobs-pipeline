"""Shared pytest fixtures. pytest loads this file automatically, no import needed."""

import psycopg
import pytest

from nl_jobs import db
from nl_jobs.config import load_settings
from nl_jobs.migrate import apply_migrations


@pytest.fixture
def db_conn():
    """A migrated connection whose changes are rolled back after the test."""
    try:
        conn = db.connect(load_settings(), connect_timeout=3)
    except (KeyError, psycopg.OperationalError) as exc:
        pytest.skip(f"Postgres not reachable ({exc!r}); run make up and use make test")
    try:
        apply_migrations(conn)
        yield conn
    finally:
        conn.rollback()
        conn.close()
