import pytest

import nl_jobs
from nl_jobs.config import load_settings


def test_package_imports_from_installed_src():
    assert nl_jobs.__version__ == "0.1.0"


def test_load_settings_reads_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_PORT", "6000")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")

    settings = load_settings()

    assert settings.pg_port == 6000
    assert "secret" not in repr(settings)


def test_load_settings_requires_password(monkeypatch):
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    with pytest.raises(KeyError):
        load_settings()
