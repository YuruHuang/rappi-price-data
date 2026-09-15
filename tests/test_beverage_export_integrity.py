"""End-to-end checks for beverage output linkage and optional detail joins."""
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rappi_co import beverages
from rappi_co.collect import search as collector


def _source(tmp_path, monkeypatch, *, country="co", slug="centro-plaza-bolivar", terms=None):
    monkeypatch.setattr(collector, "search", lambda *args, **kwargs: {
        "stores": [{"store_id": "001", "store_name": "Shop", "products": [{
            "product_id": "002", "name": "Agua 500 ml", "price": 100,
            "quantity": 500, "unit_type": "ml", "presentation": "1 x 500 ml",
            "is_available": True, "attributes": {"volume": "500 mL"},
        }]}]})
    path, _ = collector.run(slug, terms or ["agua"], tmp_path / "raw", country=country,
                            min_delay=0, max_delay=0)
    return path


def _plan(terms=None):
    return beverages.plan_country("co", ["centro-plaza-bolivar"], terms or ["agua"])


def test_export_retains_keys_currency_and_uncertainty(tmp_path, monkeypatch):
    source = _source(tmp_path, monkeypatch)
    result = beverages.export_country(_plan(), {"centro-plaza-bolivar": source}, tmp_path)
    with Path(result["audit_csv"]).open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["store_id"] == "001" and row["product_id"] == "002"
    assert row["currency"] == "COP" and row["price_local"] == "100.0"
    assert row["sugar_g_per_100ml"] == row["abv_pct"] == ""
    assert row["price_per_liter_local"] == "200.0"
    manifest = json.loads(Path(result["manifest"]).read_text())
    assert manifest["complete"] is True
    assert manifest["plan"]["full_protocol"] is False
    lineage = manifest["inputs"]["centro-plaza-bolivar"]
    assert lineage["items"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    source_manifest = source.with_name(source.name.replace("search_items_", "search_manifest_")).with_suffix(".json")
    assert lineage["manifest"]["sha256"] == hashlib.sha256(source_manifest.read_bytes()).hexdigest()
    assert len(lineage["raw_responses"]) == 1
    assert not (Path(result["manifest"]).parent / "INCOMPLETE").exists()


def test_export_rejects_wrong_country_archive(tmp_path, monkeypatch):
    source = _source(tmp_path, monkeypatch, country="mx", slug="centro-bellas-artes")
    with pytest.raises(ValueError, match="(?i)(country|currency|source|manifest)"):
        beverages.export_country(_plan(), {"centro-plaza-bolivar": source}, tmp_path)


def test_export_rejects_unexecuted_planned_queries(tmp_path, monkeypatch):
    source = _source(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="(?i)(queries|query|source|manifest)"):
        beverages.export_country(_plan(["agua", "cerveza"]), {"centro-plaza-bolivar": source}, tmp_path)


def test_export_rejects_extra_sources(tmp_path, monkeypatch):
    source = _source(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="(?i)(source|location|address)"):
        beverages.export_country(_plan(), {"centro-plaza-bolivar": source, "unplanned": source}, tmp_path)


def _row():
    return {"country_code": "co", "zone_slug": "zone", "store_id": "001", "product_id": "002"}


def test_failed_detail_cannot_inject_nutrition():
    detail = {**_row(), "detail_status": "identity_mismatch",
              "product_information": "Azúcares 10g por 100ml",
              "ingredients_text": "azúcar", "nutrition_text": "ABV: 5%"}
    row = beverages.overlay_details([_row()], [detail])[0]
    assert row["detail_status"] == "identity_mismatch"
    assert row["product_information"] == row["ingredients_text"] == row["nutrition_text"] == ""


@pytest.mark.parametrize("details", [[_row()], [{**_row(), "store_id": "another"}]])
def test_duplicate_or_unmatched_detail_rejected(details):
    if details[0]["store_id"] == "001":
        details = details * 2
    with pytest.raises(ValueError, match="duplicate or unmatched"):
        beverages.overlay_details([_row()], details)


def test_successful_detail_requires_evidence():
    with pytest.raises(ValueError, match="identity and evidence"):
        beverages.overlay_details([_row()], [{**_row(), "detail_status": "ok",
                                              "product_information": "ABV: 5%"}])


def test_paired_coverage_keeps_original_category_cohort():
    before = [{**_row(), "beverage_category": "review", "sugar_g_per_100ml": None}]
    after = [{**_row(), "beverage_category": "ssb", "sugar_g_per_100ml": 10,
              "detail_status": "ok"}]
    row = beverages.paired_coverage(before, after)[0]
    assert row["baseline_category"] == "review"
    assert row["observations"] == row["classification_changed"] == 1
    assert row["sugar_g_per_100ml_before"] == 0
    assert row["sugar_g_per_100ml_after"] == row["sugar_g_per_100ml_gained"] == 1
    assert row["sugar_g_per_100ml_lost"] == 0


def test_verified_detail_improvement_survives_export(tmp_path, monkeypatch):
    from rappi_co.collect.product_details import parse_snapshot
    from rappi_co.parsers.beverage_search import replay_search

    source = _source(tmp_path, monkeypatch)
    details = tmp_path / "details.csv"
    original = replay_search(source)[0][0]
    zone = _plan()["addresses"][0]
    original.update(zone_slug=zone["slug"], latitude=zone["lat"], longitude=zone["lng"])
    snapshot = {"url": "https://www.rappi.com.co/p/test", "status": 200, "locale": "es-CO",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "text": "Información del producto\nIngredientes: agua, azúcar. Azúcares 10g por 100ml",
                "identity": {"name": original["name"], "product_id": "002", "store_id": "001",
                             "method": "pdp_primary_ids_and_heading"},
                "ssr_primary_product": {"name": original["name"], "id": "002", "storeId": "001"},
                "ssr_location": {"lat": zone["lat"], "lng": zone["lng"], "autoLocation": False},
                "visible_primary_store_links": ["/tiendas/001-shop"], "product_heading_names": [original["name"]],
                "product_view_verified": True, "primary_store_visible_matches": True, "location_verified": True}
    detail = parse_snapshot(snapshot, original)
    evidence = tmp_path / "evidence.json"
    detail["detail_evidence_path"] = str(evidence)
    evidence.write_text(json.dumps({"schema_version": 1, "input": original, "snapshot": snapshot, "result": detail}))
    detail["detail_evidence_sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    with details.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(detail))
        writer.writeheader()
        writer.writerow(detail)
    result = beverages.export_country(_plan(), {"centro-plaza-bolivar": source}, tmp_path, details)
    with Path(result["audit_csv"]).open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["beverage_category"] == "ssb" and row["sugar_g_per_100ml"] == "10.0"
    with Path(result["detail_comparison_csv"]).open(encoding="utf-8-sig", newline="") as handle:
        delta = next(csv.DictReader(handle))
    assert delta["baseline_category"] == "water" and delta["sugar_g_per_100ml_gained"] == "1"


def test_canonical_product_page_cannot_inject_into_store_observation():
    detail = {**_row(), "detail_status": "captured_product_page", "detail_scope": "product",
              "product_information": "Azúcares 10g por 100ml"}
    row = beverages.overlay_details([_row()], [detail])[0]
    assert row["product_information"] == ""


def test_claimed_success_with_product_scope_is_rejected():
    detail = {**_row(), "detail_status": "ok", "detail_scope": "product",
              "product_information": "Azúcares 10g por 100ml",
              "detail_identity_method": "pdp_primary_ids_and_heading",
              "detail_url": "https://www.rappi.com.co/p/test",
              "detail_retrieved_at": "2026-01-01T00:00:00Z", "detail_evidence_path": "evidence.json"}
    with pytest.raises(ValueError, match="(?i)(scope|identity|observation)"):
        beverages.overlay_details([_row()], [detail])
