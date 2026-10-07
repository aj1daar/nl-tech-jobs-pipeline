"""Postgres connections."""

from typing import Any

import psycopg

from nl_jobs.config import Settings


def connect(settings: Settings, **kwargs: Any) -> psycopg.Connection:
    # Without a timeout, an unreachable host (a dropped IPv6 "localhost") hangs forever.
    kwargs.setdefault("connect_timeout", 10)
    # Keyword arguments instead of a URL: no escaping problems with special characters.
    return psycopg.connect(
        host=settings.pg_host,
        port=settings.pg_port,
        dbname=settings.pg_db,
        user=settings.pg_user,
        password=settings.pg_password,
        application_name="nl-jobs",
        **kwargs,
    )
