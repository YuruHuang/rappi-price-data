"""Protocol and review-cohort checks for the beverage workflow."""
import pytest

from rappi_co.beverages import plan_country, paired_coverage, review_sample


def test_full_plan_reuses_eight_locations_and_records_finite_queries():
    plans = [plan_country(c) for c in ("ar", "co", "pe", "mx")]
    assert sum(p["requests"] for p in plans) == 356
    assert sum(len(p["addresses"]) for p in plans) == 8
    assert all(p["full_protocol"] for p in plans)
    assert {p["currency"] for p in plans} == {"ARS", "COP", "PEN", "MXN"}
    for p in plans:
        assert len(p["queries"]) == len(set(p["queries"]))
        assert {"agua", "gaseosa", "cerveza"}.issubset(p["queries"])
        assert "unknown" in p["catalog_completeness"]


def test_partial_protocol_cannot_be_reported_as_full():
    assert not plan_country("co", terms=["agua"])["full_protocol"]
    assert not plan_country("co", addresses=["centro-plaza-bolivar"])["full_protocol"]
    with pytest.raises(ValueError):
        plan_country("co", terms=[" "])
    with pytest.raises(ValueError):
        plan_country("co", addresses=["centro-plaza-bolivar"] * 2)


def _row(n, category="review", zone="z"):
    return {"country_code": "co", "zone_slug": zone, "store_id": "001", "product_id": str(n),
            "beverage_category": category, "beverage_flags": ["conflict"] if n % 2 else []}


def test_sample_is_stable_preserves_strata_and_has_no_duplicates():
    rows = [_row(n, cat, zone) for cat in ("water", "review") for zone in ("a", "b")
            for n in range(20)]
    # Input identities must be unique across categories within a location.
    for i, row in enumerate(rows):
        row["product_id"] = str(i)
    sample = review_sample(rows)
    assert sample == review_sample(list(reversed(rows)))
    assert len(sample) == 48
    assert len({(r["zone_slug"], r["product_id"]) for r in sample}) == 48
    assert {(r["zone_slug"], r["beverage_category"]) for r in sample} == {
        (zone, cat) for zone in ("a", "b") for cat in ("water", "review")}


def test_paired_coverage_rejects_changed_cohort_and_records_lost_values():
    before = [{**_row(1), "abv_pct": 5}]
    after = [{**_row(1), "abv_pct": None, "detail_status": "ok"}]
    record = paired_coverage(before, after)[0]
    assert record["abv_pct_lost"] == 1 and record["abv_pct_gained"] == 0
    with pytest.raises(ValueError, match="identical"):
        paired_coverage(before, [_row(2)])


def test_ssb_candidate_sheet_distinguishes_confirmation_from_unknown(tmp_path, monkeypatch):
    import csv
    from pathlib import Path
    from rappi_co.beverages import export_country
    from rappi_co.collect import search as collector

    names = ["Gaseosa Original 500 ml", "Gaseosa con azúcar 500 ml", "Gaseosa sin azúcar 500 ml"]
    monkeypatch.setattr(collector, "search", lambda *a, **kw: {"stores": [{
        "store_id": "001", "store_name": "Shop", "products": [
            {"product_id": str(i), "name": name, "price": 100,
             "quantity": 500, "unit_type": "ml", "presentation": "1 x 500 ml"}
            for i, name in enumerate(names, 1)]}]})
    source, _ = collector.run("centro-plaza-bolivar", ["gaseosa"], tmp_path / "raw",
                              country="co", min_delay=0, max_delay=0)
    plan = plan_country("co", ["centro-plaza-bolivar"], ["gaseosa"])
    result = export_country(plan, {"centro-plaza-bolivar": source}, tmp_path)
    with Path(result["ssb_candidates_csv"]).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {r["product_id"] for r in rows} == {"1", "2"}
    assert {r["ssb_candidate_status"] for r in rows} == {"sweetening_unconfirmed", "confirmed_sugar_sweetened"}
    assert all(not r["sugar_g_per_100ml"] for r in rows)
    assert result["counts"]["comparison"] == 1
