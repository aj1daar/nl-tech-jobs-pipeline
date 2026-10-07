# nl-tech-jobs-pipeline

A daily pipeline that collects Dutch tech job postings from public ATS APIs, normalises them into one model, and joins them against the IND register of recognised visa sponsors.

It exists to answer three questions no job board filters on: which companies can sponsor a visa, which postings genuinely accept juniors, and which require Dutch.

## How the pipeline works

```
        EXTRACT                          LOAD (raw, append-only)              TRANSFORM (planned)
 ATS job board APIs   --ingest-->        raw.board_fetches             (Greenhouse so far)                                                   >--dbt-->  staging -> intermediate -> marts
 iwwz sponsor export  --ingest-sponsors->raw.sponsor_export_fetches   /
                                         raw.sponsor_export_rows
```

It is an ELT pipeline: data is loaded exactly as received, and all cleaning happens afterwards in SQL.

**1. Which companies.** `dbt/seeds/companies.csv` lists the companies and the ATS board each one uses. It is the only place a company is added or switched off.

**2. Extract.** `python -m nl_jobs ingest greenhouse` calls the public board API once per active company, one second apart, with retries for timeouts, 429 and 5xx. `python -m nl_jobs ingest-sponsors` downloads the sponsor register from the iwwz API in one request.

**3. Load.** Every attempt becomes a row in Postgres, including the ones that went wrong:

| Table | One row per | What it holds |
|---|---|---|
| `raw.board_fetches` | fetch of one board | the full JSON response, plus an outcome: `ok`, `empty`, `not_found` or `failed` |
| `raw.sponsor_export_fetches` | fetch of the sponsor export | the outcome (11 kinds, from `ok` to `unauthorized` to `count_mismatch`) |
| `raw.sponsor_export_rows` | sponsor per accepted export | the sponsor object as sent, with the export's timestamp |

Raw tables are append-only: the database rejects updates and deletes. Running the same day twice adds new attempts next to the old ones. Each row carries a `run_date`, the day the run is for, so a past day can be rebuilt or backfilled.

**4. Transform (not built yet).** dbt will pick one attempt per board per day, split the JSON into one row per posting, track postings that change or disappear, and join companies to the sponsor register by KvK number.

**5. Schedule (not built yet).** A daily run is these same commands in order: `migrate`, `ingest`, `ingest-sponsors`, then dbt. Airflow or a plain cron entry can call them.

| Stage | Status |
|---|---|
| Seed list (13 companies) | done |
| Greenhouse ingestion | done, runs against the live API |
| Sponsor export ingestion | done, runs against the live API (13,148 sponsors per snapshot) |
| Lever, Ashby, Workable, Recruitee, SmartRecruiters | not built |
| dbt models | not built |
| Scheduling | not built |

## Run it locally

Needs Docker, [uv](https://docs.astral.sh/uv/) and make.

```sh
cp .env.example .env   # then set a local password
make install           # Python 3.12 venv + dependencies
make up                # Postgres 18 on 127.0.0.1:5433
make migrate           # create the raw tables
make check             # lint + tests
make ingest            # fetch every active Greenhouse board in the seed
```

Then look at what landed with `make psql`:

```sql
select run_date, board_slug, outcome, job_count from raw.board_fetches order by fetch_id desc limit 10;
```

`make db-reset` deletes the local database volume.

## Sponsor register (iwwz)

The IND register of recognised sponsors comes from the ik-wil-werk-zoeken API
(`GET /api/export/sponsors`), not from this repo. It needs an API key, which is never
committed. Locally, either put it in your gitignored `.env` or export it in your shell
(an exported value wins over `.env`):

```sh
export IWWZ_API_KEY=...          # PowerShell: $env:IWWZ_API_KEY = '...'
make sponsors
```

In production the scheduler supplies it. The API allows 30 requests per key per hour.

## Known limitations

- Only the 13 companies in `dbt/seeds/companies.csv` are collected, and only the 2 on Greenhouse are fetched so far.
- `kvk_number` is empty for every company in the seed, so the sponsor join has nothing to match on yet.
- Postings on job boards or career pages outside the six supported ATS platforms are not collected.

Design and decisions: [docs/architecture.md](docs/architecture.md).
