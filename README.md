# nl-tech-jobs-pipeline

A daily pipeline that collects Dutch tech job postings from public ATS APIs, normalises them into one model, and joins them against the IND register of recognised visa sponsors.

It exists to answer three questions no job board filters on: which companies can sponsor a visa, which postings genuinely accept juniors, and which require Dutch.

## Run it locally

Needs Docker, [uv](https://docs.astral.sh/uv/) and make.

```sh
cp .env.example .env   # then set a local password
make install           # Python 3.12 venv + dependencies
make up                # Postgres on 127.0.0.1:5433
make migrate           # create the raw schema
make check             # lint + tests

uv run --env-file .env python -m nl_jobs ingest greenhouse   # boards from dbt/seeds/companies.csv
```

`make psql` opens a shell on the database. `make db-reset` deletes the local volume.

## Sponsor register (iwwz)

The IND register of recognised sponsors comes from the ik-wil-werk-zoeken API
(`GET /api/export/sponsors`), not from this repo. It needs an API key, which is never
written to a file here. For a one-off run, export it in your shell first:

```sh
export IWWZ_API_KEY=...          # PowerShell: $env:IWWZ_API_KEY = '...'
make sponsors
```

Leave `IWWZ_API_KEY=` empty in `.env`. In production the scheduler supplies it.

## Known limitations

- Work in progress: Greenhouse and the sponsor export land in the raw layer. No dbt models or scheduling yet.
- The sponsor client has not run against the live API yet, and its recorded test fixture is still missing.
- Only the 13 companies in `dbt/seeds/companies.csv` are collected. Postings on job boards or company career pages outside the six supported ATS platforms are not.

Design and decisions: [docs/architecture.md](docs/architecture.md).
