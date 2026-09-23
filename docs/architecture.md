# Architecture

## Data flow

```
ATS JSON APIs  ->  Python ingestion (src/nl_jobs)  ->  raw schema (immutable JSON)
               ->  dbt staging -> intermediate -> marts  ->  joined with IND sponsor register
Airflow runs the whole chain once a day.
```

## Design principles

1. **Raw data is immutable.** Original JSON lands with an ingestion timestamp and is never updated or deleted. Everything downstream can be rebuilt from it.
2. **Reruns are idempotent.** Running the same day twice gives identical output with no duplicates.
3. **Null is not false.** Unknown stays `null`. For example, a posting that does not mention Dutch has `requires_dutch = null`, not `false`.
4. **Failure modes are distinct.** An empty board, a 404, and a failed request are stored as three different outcomes.
5. **Postings change.** An edited posting updates in place; a posting that disappears is marked closed, never deleted.
6. **Snapshots.** It must be possible to ask what was open on a past date, not only what is open now.

## Repository layout

| Path | Purpose |
|---|---|
| `src/nl_jobs/` | Ingestion package. src layout, so tests run against the installed package. |
| `src/nl_jobs/sources/` | One module per ATS, same plain function names, no base class. |
| `tests/fixtures/` | Recorded API responses. Tests never call the network. |
| `sql/migrations/` | Numbered DDL for the raw schema. Owned outside dbt so raw data survives any dbt rebuild. |
| `dbt/` | Transformation project (checkpoint 4). |
| `airflow/dags/` | Orchestration (checkpoint 5). Airflow runs in its own container, not in the project venv. |

## Decisions log

| Date | Decision | Reason |
|---|---|---|
| 2026-09-23 | uv for Python version, venv and lockfile | Installs 3.12 next to the system 3.14; `uv.lock` gives identical installs locally, in CI and on the VPS. |
| 2026-09-23 | Makefile for task running | Standard in data repos, works unchanged on Linux VPS and CI. Recipes stay single commands so they also run under cmd.exe. |
| 2026-09-23 | Local Postgres 16 on host port 5433 | Matches the existing project's version; 5432 is already in use. Bound to 127.0.0.1 only. |
| 2026-09-23 | LF line endings via `.gitattributes` | Files are copied into Linux containers, where CRLF breaks shell scripts. |
