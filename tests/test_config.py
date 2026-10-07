import pytest

import nl_jobs
from nl_jobs.config import IWWZ_EXPORT_URL_DEFAULT, load_iwwz_settings, load_settings


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


def test_iwwz_settings_read_key_from_env_and_hide_it(monkeypatch):
    monkeypatch.setenv("IWWZ_API_KEY", "k-123")
    monkeypatch.delenv("IWWZ_EXPORT_URL", raising=False)

    settings = load_iwwz_settings()

    assert settings.api_key == "k-123"
    assert settings.export_url == IWWZ_EXPORT_URL_DEFAULT
    assert "k-123" not in repr(settings)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_iwwz_key_missing_or_empty_raises(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("IWWZ_API_KEY", raising=False)
    else:
        monkeypatch.setenv("IWWZ_API_KEY", value)

    with pytest.raises(KeyError, match="IWWZ_API_KEY"):
        load_iwwz_settings()


def test_iwwz_empty_url_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("IWWZ_API_KEY", "k-123")
    monkeypatch.setenv("IWWZ_EXPORT_URL", "")

    assert load_iwwz_settings().export_url == IWWZ_EXPORT_URL_DEFAULT


def test_iwwz_url_must_be_https(monkeypatch):
    monkeypatch.setenv("IWWZ_API_KEY", "k-123")
    monkeypatch.setenv("IWWZ_EXPORT_URL", "http://api.nogoibay.org/api/export/sponsors")

    with pytest.raises(ValueError, match="https"):
        load_iwwz_settings()


def test_board_settings_do_not_need_the_iwwz_key(monkeypatch):
    monkeypatch.delenv("IWWZ_API_KEY", raising=False)
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")

    load_settings()
