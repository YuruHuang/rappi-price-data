# tests for the guardrail helpers + a live integration check against whatever the last
# enumeration produced (skipped if you haven't run `scrapy crawl stores` yet).
import csv
from pathlib import Path

import pytest

from rappi_co import checks
from rappi_co import settings as S


def test_store_types_parse():
    assert checks._store_types({"store_types": '["market"]'}) == ["market"]
    assert checks._store_types({"store_types": '["a", "b"]'}) == ["a", "b"]
    assert checks._store_types({"store_types": ""}) == []


def test_preflight_passes_on_shipped_config():
    checks._FAILS.clear()
    checks.check_preflight()
    assert not checks._FAILS, checks._FAILS


def _latest_stores():
    files = list((Path(S.PROJECT_ROOT) / "data" / "raw").glob("*/stores_*.csv"))
    # pick the largest = the real enumeration (the menu spider re-emits tiny stores files).
    return max(files, key=lambda p: p.stat().st_size) if files else None


def test_enumeration_coverage_if_present():
    # integration: if an enumeration exists, it must clear the coverage guardrails
    # (enough stores + real supermarket/convenience/pharmacy chains present).
    f = _latest_stores()
    if not f:
        pytest.skip("no stores csv yet — run `scrapy crawl stores` first")
    address = f.parent.name
    checks._FAILS.clear()
    checks.check_enumeration(address)
    assert not checks._FAILS, checks._FAILS
