from pathlib import Path

import pytest

from rappi_co.configs import (
    ConfigError,
    STUDY_CATEGORIES,
    load_brand_terms,
    load_study_profile,
    study_queries,
)


ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "study"


def test_all_country_profiles_load():
    expected = {
        "ar": ("ARS", 27),
        "co": ("COP", 32),
        "pe": ("PEN", 30),
        "mx": ("MXN", 32),
    }
    for code, (currency, query_count) in expected.items():
        profile = load_study_profile(code, CONFIG)
        assert profile["currency"] == currency
        assert len(profile["zones"]) == 2
        assert len(study_queries(profile)) == query_count


def test_each_country_has_its_service_host():
    expected = {
        "ar": "services.rappi.com.ar",
        "co": "services.grability.rappi.com",
        "pe": "services.rappi.pe",
        "mx": "services.mxgrability.rappi.com",
    }
    for code, host in expected.items():
        profile = load_study_profile(code, CONFIG)
        assert profile["services_url"] == f"https://{host}"


def test_generic_scope_is_fixed_and_first():
    profile = load_study_profile("co", CONFIG)
    assert study_queries(profile)[:6] == [
        "bolsas de nicotina",
        "cigarrillos electronicos",
        "vapeador",
        "vapeadores",
        "productos de tabaco calentado",
        "cigarrillos",
    ]


def test_brand_rows_have_category_and_scope():
    for code in ("ar", "co", "pe", "mx"):
        rows = load_brand_terms(CONFIG / f"brand_terms_{code}.yml")
        assert {row["category"] for row in rows}.issubset(STUDY_CATEGORIES)
        assert {row["market_scope"] for row in rows}.issubset(
            {"international", "local_market"})


def test_brand_cap_fails_loud(tmp_path):
    groups = {category: [] for category in STUDY_CATEGORIES}
    groups["cigarettes"] = [
        {"brand": f"Brand {i}", "query": f"brand {i} cigarrillos",
         "market_scope": "international", "match": "distinctive"}
        for i in range(11)
    ]
    import yaml
    path = tmp_path / "brand_terms_xx.yml"
    path.write_text(yaml.safe_dump({"brand_terms": groups}), encoding="utf-8")
    with pytest.raises(ConfigError, match="maximum is 10"):
        load_brand_terms(path)


def test_duplicate_zone_slugs_fail_loud(tmp_path):
    from rappi_co.configs import load_zones
    path = tmp_path / "zones_xx.yml"
    path.write_text(
        "zones:\n  - {slug: same, lat: 1, lng: 2}\n  - {slug: same, lat: 3, lng: 4}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="duplicate zone slug"):
        load_zones(path)
