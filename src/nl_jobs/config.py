"""Runtime settings, read from environment variables in one place."""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    pg_host: str
    pg_port: int
    pg_db: str
    pg_user: str
    # repr=False keeps the password out of logs and tracebacks that print Settings.
    pg_password: str = field(repr=False)


def load_settings() -> Settings:
    return Settings(
        pg_host=os.environ.get("POSTGRES_HOST", "localhost"),
        pg_port=int(os.environ.get("POSTGRES_PORT", "5433")),
        pg_db=os.environ.get("POSTGRES_DB", "nl_jobs"),
        pg_user=os.environ.get("POSTGRES_USER", "nl_jobs"),
        # No default: a missing password should fail loudly, not connect with a guess.
        pg_password=os.environ["POSTGRES_PASSWORD"],
    )
