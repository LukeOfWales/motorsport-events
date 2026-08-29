"""Shared test fixtures/helpers."""
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()
