"""Regression tests for archive, observation-detail, and export boundaries."""
import csv
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rappi_co import beverages
from rappi_co.collect import search as collector
from rappi_co.collect.product_details import parse_snapshot
from rappi_co.enrich.beverage_fields import enrich_beverage
from rappi_co.parsers.beverage_search import replay_search


def later_sighting(row, field, value):
    return {**row, "source_conflicts_json": [{"fields": {
        field: {"first": row.get(field), "later": value}}}]}


@pytest.mark.parametrize("later_name", [
    "2 Agua 500mL", "Pack Agua 500mL", "Agua 2 x 1 500mL", "6x500mLTapa Agua",
])
def test_later_explicit_pack_uncertainty_clears_original_derived_total(later_name):
    row = {"name": "Agua 500mL", "pack_format_raw": "1 x 500 mL"}
    result = enrich_beverage(later_sighting(row, "name", later_name))
    assert result["pack_count"] is None
    assert result["total_volume_ml"] is None
    assert "cross_query_composition_conflict" in result["beverage_flags"]


@pytest.mark.parametrize("field,first,later,numeric", [
    ("short_description", "5% ABV", "<5% ABV", "abv_pct"),
    ("short_description", "Alcohol 5%", "Alcohol 5% w/w", "abv_pct"),
    ("short_description", "5g de azúcar por 100ml", "menos de 5g de azúcar por 100ml", "sugar_g_per_100ml"),
    ("short_description", "Azúcares 5g por 100ml", "Azúcares 5g por 100g", "sugar_g_per_100ml"),
    ("short_description", "Azúcares 5g por 100ml", "Azúcares 5g", "sugar_g_per_100ml"),
    ("attributes_json", {"abv_pct": 5}, {"abv_pct": True}, "abv_pct"),
    ("attributes_json", {"sugar_g_per_100ml": 5}, {"sugar_g_per_100ml": -5}, "sugar_g_per_100ml"),
])
def test_later_explicit_composition_uncertainty_clears_first_number(field, first, later, numeric):
    row = {"name": "Cerveza 330 ml" if numeric == "abv_pct" else "Gaseosa 500 ml", field: first}
    assert enrich_beverage(row)[numeric] == 5
    result = enrich_beverage(later_sighting(row, field, later))
    assert result[numeric] is None
    assert "cross_query_conflicting_" + numeric in result["beverage_flags"]


@pytest.mark.parametrize("field,first,numeric,expected", [
    ("short_description", "5% ABV", "abv_pct", 5),
    ("short_description", "Azúcares 5g por 100ml", "sugar_g_per_100ml", 5),
    ("pack_format_raw", "1 x 500 ml", "total_volume_ml", 500),
])
def test_later_missing_text_preserves_original_explicit_evidence(field, first, numeric, expected):
    row = {"name": "Cerveza 500 ml" if numeric == "abv_pct" else "Gaseosa 500 ml", field: first}
    result = enrich_beverage(later_sighting(row, field, ""))
    assert result[numeric] == expected
    assert "cross_query_composition_conflict" not in result["beverage_flags"]


def test_later_invalid_operand_clears_derived_sugar_but_preserves_independent_total():
    row = {"name": "Gaseosa 500 ml", "pack_format_raw": "1 x 500 ml",
           "short_description": "Volumen total: 500ml",
           "attributes_json": {"sugar_g_per_serving": 10, "serving_volume_ml": 200}}
    result = enrich_beverage(later_sighting(row, "attributes_json", {
        "sugar_g_per_serving": 10, "serving_volume_ml": 0}))
    assert result["serving_volume_ml"] is None
    assert result["sugar_g_per_100ml"] is None
    assert result["total_volume_ml"] == 500
    result = enrich_beverage(later_sighting(row, "name", "2 Gaseosa 500 ml"))
    assert result["pack_count"] is None
    assert result["total_volume_ml"] == 500


def test_later_invalid_serving_preserves_independently_explicit_sugar_concentration():
    row = {"name": "Gaseosa 500 ml", "attributes_json": {
        "sugar_g_per_serving": 10, "serving_volume_ml": 200, "sugar_g_per_100ml": 5}}
    result = enrich_beverage(later_sighting(row, "attributes_json", {
        "sugar_g_per_serving": 10, "serving_volume_ml": 0, "sugar_g_per_100ml": 5}))
    assert result["serving_volume_ml"] is None
    assert result["sugar_g_per_100ml"] == 5


def collection(tmp_path, monkeypatch, **product_fields):
    product = {"product_id": "002", "master_product_id": "1234", "name": "Agua 500 ml",
               "price": 100, "quantity": 500, "unit_type": "ml", "presentation": "1 x 500 ml",
               **product_fields}
    monkeypatch.setattr(collector, "search", lambda *a, **kw: {
        "stores": [{"store_id": "001", "store_name": "Shop", "products": [product]}]})
    path, _ = collector.run("centro-plaza-bolivar", ["agua"], tmp_path / "raw", country="co",
                            min_delay=0, max_delay=0)
    plan = beverages.plan_country("co", ["centro-plaza-bolivar"], ["agua"])
    return path, plan


def observed_row(source, plan):
    row = replay_search(source)[0][0]
    zone = plan["addresses"][0]
    return {**row, "country_code": "co", "zone_slug": zone["slug"],
            "latitude": zone["lat"], "longitude": zone["lng"]}


def evidenced_detail(tmp_path, row, *, text="Información del producto\nIngredientes: agua, azúcar. Azúcares 10g por 100ml"):
    retrieved = datetime.now(timezone.utc).isoformat()
    location = {"lat": row["latitude"], "lng": row["longitude"], "autoLocation": False}
    snapshot = {
        "url": "https://www.rappi.com.co/p/agua-1234", "status": 200, "locale": "es-CO",
        "retrieved_at": retrieved, "text": text, "product_view_verified": True,
        "location_verified": True, "ssr_location": location, "primary_store_visible_matches": True,
        "visible_primary_store_links": ["/tiendas/001-shop"],
        "product_heading_names": [row["name"]],
        "identity": {"name": row["name"], "product_id": row["product_id"], "store_id": row["store_id"],
                     "master_product_id": row["master_product_id"], "method": "pdp_primary_ids_and_heading"},
        "ssr_primary_product": {"name": row["name"], "id": row["product_id"], "storeId": row["store_id"],
                                "masterProductId": row["master_product_id"]},
    }
    detail = parse_snapshot(snapshot, row)
    evidence = tmp_path / "evidence.json"
    detail["detail_evidence_path"] = str(evidence)
    evidence.write_text(json.dumps({"schema_version": 1, "input": row, "snapshot": snapshot, "result": detail}))
    detail["detail_evidence_sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    return detail, evidence


def test_declared_ok_with_nonexistent_evidence_is_rejected_without_mutation(tmp_path, monkeypatch):
    source, plan = collection(tmp_path, monkeypatch)
    row = observed_row(source, plan)
    detail, evidence = evidenced_detail(tmp_path, row)
    evidence.unlink()
    original = dict(row)
    with pytest.raises(ValueError, match="evidence"):
        beverages.overlay_details([row], [detail])
    assert row == original


@pytest.mark.parametrize("tamper", ["description", "source_time", "name", "hash", "location"])
def test_detail_evidence_and_source_observation_must_agree(tmp_path, monkeypatch, tamper):
    source, plan = collection(tmp_path, monkeypatch)
    row = observed_row(source, plan)
    detail, evidence = evidenced_detail(tmp_path, row)
    if tamper == "description":
        detail["product_information"] = "Azúcares 99 g por 100 ml"
    elif tamper == "name":
        row["name"] = "Agua 1500 ml"
    elif tamper == "hash":
        evidence.write_text(evidence.read_text() + " ")
    else:
        content = json.loads(evidence.read_text())
        if tamper == "source_time":
            content["input"]["scrape_timestamp"] = "20200101_010203"
        else:
            content["snapshot"]["ssr_location"]["lat"] += 0.3
        evidence.write_text(json.dumps(content))
        detail["detail_evidence_sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="(?i)(evidence|identity|source|location|observation)"):
        beverages.overlay_details([row], [detail])


def test_verified_evidence_replays_and_enriches(tmp_path, monkeypatch):
    source, plan = collection(tmp_path, monkeypatch)
    row = observed_row(source, plan)
    detail, _ = evidenced_detail(tmp_path, row)
    result = beverages._enrich(beverages.overlay_details([row], [detail]))[0]
    assert result["sugar_g_per_100ml"] == 10


@pytest.mark.parametrize("field,value", [("name", "Agua 2000 ml"), ("price", 200), ("store_id", "other")])
def test_replay_detects_changed_core_offer_or_conflicting_store_identity(tmp_path, monkeypatch, field, value):
    source, _ = collection(tmp_path, monkeypatch)
    manifest = json.loads(source.with_name(source.name.replace("search_items_", "search_manifest_")).with_suffix(".json").read_text())
    raw = source.parent / manifest["raw_directory"] / manifest["term_results"][0]["raw_file"]
    with gzip.open(raw, "rt") as f:
        payload = json.load(f)
    payload["stores"][0]["products"][0][field] = value
    with gzip.open(raw, "wt") as f:
        json.dump(payload, f)
    with pytest.raises(ValueError, match="(?i)(CSV|identity|store)"):
        replay_search(source)


def test_replay_rejects_an_aliased_archive_directory(tmp_path, monkeypatch):
    source, _ = collection(tmp_path, monkeypatch)
    mp = source.with_name(source.name.replace("search_items_", "search_manifest_")).with_suffix(".json")
    manifest = json.loads(mp.read_text())
    original = source.parent / manifest["raw_directory"]
    alias = source.parent / "unrelated_raw"
    original.rename(alias)
    manifest["raw_directory"] = alias.name
    mp.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="(?i)(archive|timestamp|exact|raw)"):
        replay_search(source)


def test_export_tracks_store_input_and_detects_mutating_source(tmp_path, monkeypatch):
    source, plan = collection(tmp_path, monkeypatch)
    actual = beverages._enrich
    def mutate_after_read(rows):
        result = actual(rows)
        with source.open("a") as f:
            f.write("\n")
        return result
    monkeypatch.setattr(beverages, "_enrich", mutate_after_read)
    with pytest.raises(RuntimeError, match="(?i)(input|source).*changed"):
        beverages.export_country(plan, {"centro-plaza-bolivar": source}, tmp_path)
    assert not list(tmp_path.glob("co/processed/*/beverage_manifest_*.json"))


def test_long_excel_text_is_marked_and_csv_remains_complete(tmp_path, monkeypatch):
    from openpyxl import load_workbook
    description = "Agua " + "x" * 35000
    source, plan = collection(tmp_path, monkeypatch, description=description)
    result = beverages.export_country(plan, {"centro-plaza-bolivar": source}, tmp_path)
    with Path(result["audit_csv"]).open(encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f))
    assert row["short_description"] == description
    workbook = load_workbook(result["xlsx"], read_only=True)
    sheet = workbook["items"]
    values = list(sheet.values)
    cell = values[1][values[0].index("short_description")]
    assert "TRUNCATED IN XLSX" in cell
    assert "excel_truncations" in workbook.sheetnames
    manifest = json.loads(Path(result["manifest"]).read_text())
    assert "stores" in manifest["inputs"]["centro-plaza-bolivar"]
    assert "rappi_co/parsers/search_api.py" in manifest["code_sha256"]


def test_truncation_before_nutrition_is_not_complete_description():
    from rappi_co.collect.product_details import parse_information_text
    text = "Información del producto\nBebida... Ver más\nInformación nutricional\nAzúcares 10 g por 100 ml"
    assert parse_information_text(text)["is_truncated"]


def test_boolean_price_is_not_a_monetary_amount(tmp_path, monkeypatch):
    source, _ = collection(tmp_path, monkeypatch, price=True)
    row = replay_search(source)[0][0]
    assert row["price_local"] is None and row["invalid_price_source"]
    assert beverages._number(True) is None
    assert beverages._enrich([row])[0]["price_per_liter_local"] is None


def test_zero_sugar_and_abv_remain_present_but_zero_price_has_no_unit_price():
    assert beverages._number(0) == 0
    assert beverages._number("0") == 0
    assert beverages._number(float("nan")) is None
    result = beverages._enrich([{"name": "Agua 500 ml", "pack_format_raw": "1 x 500 ml", "price_local": 0}])[0]
    assert result["price_per_liter_local"] is None
