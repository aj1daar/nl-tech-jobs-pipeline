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
        pg_host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        pg_port=int(os.environ.get("POSTGRES_PORT", "5433")),
        pg_db=os.environ.get("POSTGRES_DB", "nl_jobs"),
        pg_user=os.environ.get("POSTGRES_USER", "nl_jobs"),
        # No default: a missing password should fail loudly, not connect with a guess.
        pg_password=os.environ["POSTGRES_PASSWORD"],
    )


IWWZ_EXPORT_URL_DEFAULT = "https://api.nogoibay.org/api/export/sponsors"


@dataclass(frozen=True)
class IwwzSettings:
    """Settings for the sponsor export only, so board ingestion never needs the key."""

    export_url: str
    # repr=False: the key must never show up in a log line or a traceback.
    api_key: str = field(repr=False)


def load_iwwz_settings() -> IwwzSettings:
    # Unset and empty both count as missing: .env.example lists the name with no value.
    api_key = os.environ.get("IWWZ_API_KEY", "").strip()
    if not api_key:
        raise KeyError("IWWZ_API_KEY")
    export_url = os.environ.get("IWWZ_EXPORT_URL", "").strip() or IWWZ_EXPORT_URL_DEFAULT
    if not export_url.startswith("https://"):
        # Over plain HTTP the key would cross the network readable by anyone on the path.
        raise ValueError("IWWZ_EXPORT_URL must use https")
    return IwwzSettings(export_url=export_url, api_key=api_key)
