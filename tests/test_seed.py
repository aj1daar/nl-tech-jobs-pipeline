from pathlib import Path

import pytest

from nl_jobs.seed import active_slugs, load_companies

SEED = Path(__file__).parents[1] / "dbt" / "seeds" / "companies.csv"
HEADER = "company_id,company_name,ats,ats_slug,kvk_number,active,checked_on,notes\n"


def write_seed(tmp_path, *rows):
    path = tmp_path / "companies.csv"
    path.write_text(HEADER + "".join(row + "\n" for row in rows), encoding="utf-8")
    return path


def test_committed_seed_is_valid():
    companies = load_companies(SEED)

    assert 10 <= len(companies) <= 15


def test_blank_kvk_is_none_not_empty_string(tmp_path):
    path = write_seed(tmp_path, "adyen,Adyen,greenhouse,adyen,,true,2026-09-25,")

    [company] = load_companies(path)

    assert company.kvk_number is None


def test_active_slugs_filters_by_ats_and_active(tmp_path):
    path = write_seed(
        tmp_path,
        "adyen,Adyen,greenhouse,adyen,,true,,",
        "old,Old Co,greenhouse,old-co,,false,,",
        "mollie,Mollie,ashby,mollie,,true,,",
    )

    assert active_slugs(load_companies(path), "greenhouse") == ["adyen"]


def test_every_problem_is_reported_at_once(tmp_path):
    path = write_seed(
        tmp_path,
        "adyen,Adyen,greenhouse,adyen,1234,yes,,",
        "adyen,Adyen again,greenhouse,adyen,,true,,",
        "x,X,taleo,x,,true,,",
        ",No Id,greenhouse,no-id,,true,,",
    )

    with pytest.raises(ValueError) as excinfo:
        load_companies(path)

    message = str(excinfo.value)
    assert "line 2: active must be true or false" in message
    assert "line 2: kvk_number must be 8 digits" in message
    assert "line 3: duplicate company_id 'adyen'" in message
    assert "line 3: duplicate board greenhouse/adyen" in message
    assert "line 4: unknown ats 'taleo'" in message
    assert "line 5: missing company_id" in message
