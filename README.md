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

uv run --env-file .env python -m nl_jobs ingest greenhouse catawiki bird
```

`make psql` opens a shell on the database. `make db-reset` deletes the local volume.

## Known limitations

- Work in progress: only Greenhouse ingestion into the raw layer exists so far. No seed list, dbt models or scheduling yet.
- Only companies in the seed list are collected. Postings on job boards or company career pages outside the six supported ATS platforms are not.

Design and decisions: [docs/architecture.md](docs/architecture.md).
