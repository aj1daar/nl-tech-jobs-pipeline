"""Apply numbered SQL files from nl_jobs/migrations, each exactly once.

The files ship inside the package, so an installed copy (Airflow, cron on the VPS)
can migrate without the repo checked out.
"""

from importlib.resources import files

import psycopg

# Any constant works; it only has to be the same for every runner.
LOCK_ID = 7_314_202_609


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply pending migrations inside the caller's transaction. Returns the new filenames."""
    conn.execute("select pg_advisory_xact_lock(%s)", (LOCK_ID,))
    conn.execute("create schema if not exists meta")
    conn.execute(
        "create table if not exists meta.schema_migrations ("
        " filename text primary key,"
        " applied_at timestamptz not null default now())"
    )
    applied = {row[0] for row in conn.execute("select filename from meta.schema_migrations")}

    scripts = sorted(
        (f for f in files("nl_jobs.migrations").iterdir() if f.name.endswith(".sql")),
        key=lambda f: f.name,
    )
    new = []
    for script in scripts:
        if script.name in applied:
            continue
        conn.execute(script.read_text(encoding="utf-8"))
        conn.execute("insert into meta.schema_migrations (filename) values (%s)", (script.name,))
        new.append(script.name)
    return new
