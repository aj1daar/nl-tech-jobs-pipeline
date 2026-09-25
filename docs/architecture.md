# Architecture

## Data flow

```
ATS JSON APIs        ->  python -m nl_jobs ingest  ->  raw.board_fetches (append-only JSON)
iwwz sponsor export  ->  (planned) sponsor client ->  raw layer
raw  ->  dbt staging -> intermediate -> marts (postings joined with sponsors)
```

The CLI (`python -m nl_jobs ...`) is the unit of work. A scheduler only calls it, so a
daily run needs either Airflow or a plain cron entry, never Airflow specifically.

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
| `src/nl_jobs/migrations/` | Numbered DDL for the raw schema, applied by `python -m nl_jobs migrate`. Owned outside dbt so raw data survives any dbt rebuild. Shipped inside the package so an installed copy can migrate without the repo. |
| `dbt/` | Transformation project (checkpoint 4). |
| `airflow/dags/` | Orchestration (checkpoint 5). Airflow runs in its own container, not in the project venv. |

## Raw layer

`raw.board_fetches` holds one row per fetch attempt of one board, with the full response
in `payload` (jsonb). It is append-only: triggers reject `UPDATE`, `DELETE` and `TRUNCATE`.

| outcome | meaning | http_status | job_count | payload |
|---|---|---|---|---|
| `ok` | 200 with at least one job | 200 | > 0 | full body |
| `empty` | 200 with zero jobs, the board exists | 200 | 0 | full body |
| `not_found` | 404, wrong slug or company left the ATS | 404 | null | null |
| `failed` | no usable answer after retries: network error, 429, 5xx, bad JSON, unknown shape | status or null | null | null |

Check constraints make the combinations above the only ones the table accepts.

**Idempotency.** A rerun of the same `run_date` appends new attempts instead of replacing
rows, so raw keeps a full audit trail. Staging (checkpoint 4) will select, per
`(source, board_slug, run_date)`, the latest attempt with an answer (`ok` or `empty`), or
the latest attempt if none answered. Two runs of the same day therefore produce the same
marts.

`run_date` is the logical date of the run (UTC), passed in by the scheduler, not the wall
clock. That is what makes backfills land on the right day.

Identity values in `fetch_id` can have gaps: rolled-back inserts (tests, crashes) still
consume sequence numbers. Gaps are expected and carry no meaning.

## Sources

| Source | Status | Notes |
|---|---|---|
| Greenhouse | done | `?content=true`, 404 for unknown slugs |
| iwwz sponsor export | contract fixed, key not issued | `GET /api/export/sponsors`, `X-Api-Key`, brotli, schemaVersion 1. Field list: iwwz repo `docs/ARCHITECTURE.md`, section "Sponsor export contract". |

## Decisions log

| Date | Decision | Reason |
|---|---|---|
| 2026-09-23 | uv for Python version, venv and lockfile | Installs 3.12 next to the system 3.14; `uv.lock` gives identical installs locally, in CI and on the VPS. |
| 2026-09-23 | Makefile for task running | Standard in data repos, works unchanged on Linux VPS and CI. Recipes stay single commands so they also run under cmd.exe. |
| 2026-09-23 | Local Postgres on host port 5433 | 5432 is already in use by another local project. Bound to 127.0.0.1 only. |
| 2026-09-23 | LF line endings via `.gitattributes` | Files are copied into Linux containers, where CRLF breaks shell scripts. |
| 2026-09-25 | Local Postgres 18, not 16 | Production (iwwz VPS) runs Postgres 18.6. The earlier choice of 16 copied a local container of another project instead of production. |
| 2026-09-25 | httpx with the brotli extra | Timeouts by default, `MockTransport` for fixture tests without a mocking library; the iwwz export is served brotli-compressed. |
| 2026-09-25 | psycopg 3 | Maintained driver, native `jsonb` adaptation for raw landing. |
| 2026-09-25 | Raw grain is one row per board fetch, not per posting | The failure modes are board-level facts, and the payload stays exactly as received. Exploding into postings happens in dbt. |
| 2026-09-25 | Migrations moved from `sql/migrations/` into the package | Airflow or cron runs an installed package, not a checkout; the SQL must travel with it. |
| 2026-09-25 | Local DB host is 127.0.0.1, not localhost | On Windows, localhost resolves to ::1 first and Docker only listens on IPv4, so connects hung. Connections now also time out after 10 s. |
| 2026-09-25 | Scheduler-agnostic CLI; Airflow optional | Host is undecided and the candidate box (2 vCPU, 3.7 GB, already running the API and Postgres) may not fit Airflow. Checkpoint 5 ships both a DAG and a cron entrypoint that call the same commands. |
