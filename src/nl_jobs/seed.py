"""The company seed list: which boards to fetch.

The same CSV is a dbt seed (dbt/seeds/companies.csv), so dbt joins on exactly the list
the ingestion used. Blank cells mean unknown and load as None, matching dbt, which
loads them as SQL null.
"""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

ATS_PLATFORMS = frozenset(
    {"greenhouse", "lever", "ashby", "workable", "recruitee", "smartrecruiters"}
)
REQUIRED = ("company_id", "company_name", "ats", "ats_slug", "active")
KVK_NUMBER = re.compile(r"\d{8}")


@dataclass(frozen=True)
class Company:
    company_id: str
    company_name: str
    ats: str
    ats_slug: str
    kvk_number: str | None
    active: bool


def load_companies(path: Path) -> list[Company]:
    """Read and validate the seed. Raises ValueError listing every problem found."""
    # newline="" lets the csv module handle line endings itself, including quoted newlines.
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    companies, problems = [], []
    seen_ids, seen_boards = set(), set()
    for line, row in enumerate(rows, start=2):  # line 1 is the header
        missing = [col for col in REQUIRED if not (row.get(col) or "").strip()]
        if missing:
            problems.append(f"line {line}: missing {', '.join(missing)}")
            continue
        company = Company(
            company_id=row["company_id"].strip(),
            company_name=row["company_name"].strip(),
            ats=row["ats"].strip(),
            ats_slug=row["ats_slug"].strip(),
            kvk_number=(row.get("kvk_number") or "").strip() or None,
            active=row["active"].strip() == "true",
        )
        if row["active"].strip() not in ("true", "false"):
            problems.append(f"line {line}: active must be true or false")
        if company.ats not in ATS_PLATFORMS:
            problems.append(f"line {line}: unknown ats {company.ats!r}")
        if company.kvk_number and not KVK_NUMBER.fullmatch(company.kvk_number):
            problems.append(f"line {line}: kvk_number must be 8 digits")
        if company.company_id in seen_ids:
            problems.append(f"line {line}: duplicate company_id {company.company_id!r}")
        if (company.ats, company.ats_slug) in seen_boards:
            problems.append(f"line {line}: duplicate board {company.ats}/{company.ats_slug}")
        seen_ids.add(company.company_id)
        seen_boards.add((company.ats, company.ats_slug))
        companies.append(company)

    if problems:
        raise ValueError(f"invalid seed {path}:\n" + "\n".join(problems))
    return companies


def active_slugs(companies: list[Company], ats: str) -> list[str]:
    return [c.ats_slug for c in companies if c.active and c.ats == ats]
