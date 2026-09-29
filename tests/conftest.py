import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def load(name: str):
    text = (FIX / name).read_text(encoding="utf-8")
    return json.loads(text) if name.endswith(".json") else text


@pytest.fixture
def facts():
    return lambda ticker: load(f"facts_{ticker}.json")
