import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(*parts: str) -> bytes:
    return FIXTURES.joinpath(*parts).read_bytes()


def load_json_fixture(*parts: str):
    return json.loads(load_fixture(*parts))
