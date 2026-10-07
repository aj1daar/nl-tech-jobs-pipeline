# Recipes are single commands so they run the same under cmd.exe and sh.
-include .env
export

POSTGRES_USER ?= nl_jobs
POSTGRES_DB ?= nl_jobs

.PHONY: install up down psql migrate test lint fmt check db-reset

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
