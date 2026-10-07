# nl-tech-jobs-pipeline

A daily pipeline that collects Dutch tech job postings from public ATS APIs, normalises them into one model, and joins them against the IND register of recognised visa sponsors.

It exists to answer three questions no job board filters on: which companies can sponsor a visa, which postings genuinely accept juniors, and which require Dutch.

## Run it locally

Needs Docker, [uv](https://docs.astral.sh/uv/) and make.

```sh
cp .env.example .env   # then set a local password
make install           # Python 3.12 venv + dependencies
make up                # Postgres on localhost:5433
make check             # lint + tests
```

`make psql` opens a shell on the database. `make db-reset` deletes the local volume.

## Known limitations

- Work in progress: only the project skeleton exists so far.
- Only companies in the seed list are collected. Postings on job boards or company career pages outside the six supported ATS platforms are not.

Design and decisions: [docs/architecture.md](docs/architecture.md).
