# Recipes are single commands so they run the same under cmd.exe and sh.

# The sponsor key comes from the caller's environment, never from a file. make lets an
# included file override the environment, so an empty IWWZ_API_KEY= line in .env would
# wipe an exported key. Remember the caller's values and put them back after the include.
IWWZ_CALLER_KEY := $(value IWWZ_API_KEY)
IWWZ_CALLER_URL := $(value IWWZ_EXPORT_URL)

-include .env
export

ifneq ($(IWWZ_CALLER_KEY),)
IWWZ_API_KEY := $(IWWZ_CALLER_KEY)
endif
ifneq ($(IWWZ_CALLER_URL),)
IWWZ_EXPORT_URL := $(IWWZ_CALLER_URL)
endif
unexport IWWZ_CALLER_KEY IWWZ_CALLER_URL

POSTGRES_USER ?= nl_jobs
POSTGRES_DB ?= nl_jobs

.PHONY: install up down psql migrate ingest sponsors test lint fmt check db-reset

install:
	uv sync

up:
	docker compose up -d --wait

down:
	docker compose down

psql:
	docker compose exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

migrate:
	uv run python -m nl_jobs migrate

# Every active Greenhouse board in dbt/seeds/companies.csv.
ingest:
	uv run python -m nl_jobs ingest greenhouse

# Needs IWWZ_API_KEY exported in the shell that runs make.
sponsors:
	uv run python -m nl_jobs ingest-sponsors

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

check: lint test

# Destroys the local database volume. Local dev only.
db-reset:
	docker compose down -v
