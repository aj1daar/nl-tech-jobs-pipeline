"""Command line entrypoint. Airflow and cron both call these commands; nothing else runs the work.

python -m nl_jobs migrate
python -m nl_jobs ingest greenhouse catawiki bird --run-date 2026-09-25
"""

import argparse
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime

import httpx

from nl_jobs import db
from nl_jobs.config import load_settings
from nl_jobs.fetch_result import FetchResult, Outcome
from nl_jobs.http_client import make_client
from nl_jobs.landing import insert_fetch
from nl_jobs.migrate import apply_migrations
from nl_jobs.sources import greenhouse

# Adding a source is one line here plus its module.
SOURCES: dict[str, Callable[[httpx.Client, str], FetchResult]] = {
    greenhouse.SOURCE: greenhouse.fetch_board,
}
SECONDS_BETWEEN_BOARDS = 1.0

log = logging.getLogger("nl_jobs")


def migrate() -> int:
    with db.connect(load_settings()) as conn:
        new = apply_migrations(conn)
    log.info("applied %d migration(s): %s", len(new), ", ".join(new) or "none pending")
    return 0


def ingest(source: str, slugs: list[str], run_date: date) -> int:
    fetch_board = SOURCES[source]
    failed = 0
    with make_client() as client, db.connect(load_settings()) as conn:
        for i, slug in enumerate(slugs):
            if i:
                time.sleep(SECONDS_BETWEEN_BOARDS)
            result = fetch_board(client, slug)
            fetch_id = insert_fetch(conn, result, run_date)
            # Commit per board: a crash later in the run keeps what already landed.
            conn.commit()
            log.info(
                "%s/%s -> %s (http=%s, jobs=%s, fetch_id=%d)",
                source,
                slug,
                result.outcome,
                result.http_status,
                result.job_count,
                fetch_id,
            )
            failed += result.outcome is Outcome.FAILED
    # Empty and 404 boards are valid answers. Only failures make the run fail, so a
    # scheduler retry can fetch them again; the attempts already landed stay in raw.
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nl_jobs")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply pending SQL migrations")
    ingest_cmd = commands.add_parser("ingest", help="fetch boards and land raw JSON")
    ingest_cmd.add_argument("source", choices=sorted(SOURCES))
    ingest_cmd.add_argument("slugs", nargs="+")
    ingest_cmd.add_argument(
        "--run-date",
        type=date.fromisoformat,
        default=datetime.now(UTC).date(),
        help="logical date of the run, YYYY-MM-DD (default: today in UTC)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "migrate":
        return migrate()
    return ingest(args.source, args.slugs, args.run_date)
