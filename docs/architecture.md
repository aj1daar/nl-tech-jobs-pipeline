# Architecture

## Data flow

```
ATS JSON APIs        ->  python -m nl_jobs ingest  ->  raw.board_fetches (append-only JSON)
iwwz sponsor export  ->  python -m nl_jobs ingest-sponsors  ->  raw.sponsor_export_fetches + raw.sponsor_export_rows
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

### Sponsor export

The iwwz export lands in two append-only tables.

- `raw.sponsor_export_fetches`: one row per attempt, whatever happened. Outcomes are kept
  apart because each needs a different reaction: `ok`, `empty`, `unreachable`,
  `unauthorized` (401), `rate_limited` (429), `server_error` (5xx after retries),
  `unexpected_status`, `invalid_json`, `unsupported_schema_version`, `invalid_envelope`,
  `count_mismatch`.
- `raw.sponsor_export_rows`: one row per sponsor per accepted export, with the sponsor
  object stored as sent in `payload` (jsonb), plus `generated_at`, `schema_version` and
  `ingested_at`. Primary key `(generated_at, sponsor_id)`. Removed and merged sponsors are
  landed like any other row. Nothing is flattened or coerced: JSON null stays JSON null.

Only `ok` lands sponsor rows. A response is refused as a whole when `schemaVersion` is not
1, when `count` differs from the number of rows, when a row has no string `id` or repeats
one, or when the list is empty. There is no partial snapshot.

**Snapshots and reruns.** The server stamps every response with a new `generatedAt`, so
every accepted fetch is a full snapshot of the register (principle 6), including a second
run on the same day. Landing the same response twice (same `generatedAt`) is a no-op.
Downstream models pick the latest accepted snapshot per `run_date`, so same-day reruns
give the same marts unless the register itself changed in between.

Cost, measured on the first live snapshot (2026-10-07): 13,148 rows take 8.5 MB including
indexes, so about 3 GB a year if every daily snapshot is kept. If that becomes a problem, the fix is a downstream model that
keeps only changed rows, not a change to raw.

## Secrets

The pipeline holds one secret besides the database password: `IWWZ_API_KEY`.

- It is read from the process environment only (`load_iwwz_settings` in `config.py`).
  Unset or empty raises before any network or database work.
- It lives in its own `IwwzSettings`, not in `Settings`, so board ingestion, migrations
  and the tests never need it.
- Committed files and the image contain the name only. Locally the value comes from the
  gitignored `.env` or a shell export (the export wins). In production it comes from the
  runner: a systemd `EnvironmentFile` outside the repo or the orchestrator's secret store.
- It is never logged. The field is `repr=False`, error texts are scrubbed of the key before
  they are stored, and a test fails if the key shows up in a log record, a result or an
  error for any outcome.
- `IWWZ_EXPORT_URL` must be https, so the key cannot be sent in clear text by a typo.

## Sources

| Source | Status | Notes |
|---|---|---|
| Greenhouse | done | `?content=true`, 404 for unknown slugs |
| iwwz sponsor export | done, first live snapshot 2026-10-07 | `GET /api/export/sponsors`, `X-Api-Key`, brotli, schemaVersion 1, 13,148 rows in one response (6.2 MB of JSON, 1.1 MB on the wire as brotli), 30 requests per key per hour. Field list: iwwz repo `docs/ARCHITECTURE.md`, section "Sponsor export contract". Seen in the live data: every row has `isIndRecognizedSponsor` true and a `kvkNumber`, `locations` is null for all rows, 172 rows are removed, 12 are merged, and 7 old rows with hex ids were never enriched. The test fixture is 7 rows cut from that export. |

## Seed list

`dbt/seeds/companies.csv` is the single list of boards to fetch. The CLI reads it
(`ingest <source>` with no slugs fetches every active board of that source) and dbt loads
it as a seed, so both sides use the same companies. Validation lives in
`src/nl_jobs/seed.py` and fails on the first run with every problem listed.

| Column | Meaning |
|---|---|
| `company_id` | Stable key used everywhere downstream. Never reuse or rename. |
| `ats`, `ats_slug` | Which board to fetch. One row per board. |
| `kvk_number` | Join key for the sponsor register. Blank means unknown (null), filled in by hand. Must stay text in dbt (`column_types`) or leading zeros are lost. |
| `active` | `false` stops fetching without deleting the company, so its history stays joinable. |
| `checked_on`, `notes` | When and how the board was last confirmed. |

Companies are added only after their board API returned postings with Dutch locations.
Checked on 2026-09-25 by calling each ATS API for about 30 candidate companies.

### ATS behaviour found while building the seed

| ATS | Unknown slug returns | Consequence |
|---|---|---|
| Greenhouse | 404 | `not_found` works. |
| Lever | 404 `{"ok": false, "error": "Document not found"}`; success is a top-level JSON array | `not_found` works; the shape check differs from Greenhouse. |
| SmartRecruiters | **200 with an empty list, for any slug** | An unknown slug is indistinguishable from an empty board. Its client must check that the company exists before reporting `empty`, or `empty` loses its meaning. |
| Workable | 200 with an account name and zero jobs for many real accounts | Harmless, but none of the candidates had open postings there. |

None of the candidates has a Lever board, so the Lever client needs Dutch Lever
companies found first. Bird (Greenhouse `bird`) was left out: its board lists no Dutch
locations anymore.

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
| 2026-09-25 | Seed is a dbt seed CSV that the CLI also reads | One list for ingestion and joins; dbt can test it. The CLI resolves it relative to the working directory, so deployments run from the repo root. |
| 2026-10-05 | Sponsor export uses httpx with the brotli extra, no gzip fallback | The API negotiates brotli (5.1 MB becomes about 470 KB) and httpx advertises `br` only when it can decode it. The extra was already a dependency. A test decodes a brotli body, so removing the extra fails the suite. |
| 2026-10-05 | 401 and 429 are never retried; connection errors and 5xx are, with backoff | A bad key stays bad, and retrying a rate limit of 30 per hour only uses more of it. |
| 2026-10-05 | `IWWZ_API_KEY` is injected through the environment, never stored | See the Secrets section. `.env.example` lists the name with an empty value; the Makefile restores the caller's exported value, because make would otherwise let the empty line in `.env` override it. |
| 2026-10-05 | The sponsor key has its own settings object | Requiring it in `Settings` would make migrations, board ingestion and the database tests fail or skip without a key they do not use. |
| 2026-10-05 | Raw sponsor data is one row per sponsor per export, keyed `(generated_at, sponsor_id)`, plus one row per attempt | Mirrors what was sent, keeps every failure mode queryable, and makes each accepted fetch a dated snapshot. A newer `generatedAt` on the same day lands a new snapshot; the same one twice is a no-op. |
| 2026-10-05 | Sponsor migration lives in `src/nl_jobs/migrations/`, not `sql/migrations/` | The task text named the old folder; migrations moved into the package on 2026-09-25. |
| 2026-10-07 | The sponsor key may live in the local, gitignored `.env` | Simpler for local runs than exporting it in every shell. It still never goes into a committed file, and production still injects it. |
