"""Integrity checks for the separately published beverage first pass."""
import csv
import hashlib
import json
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]


def test_beverage_release_workbooks_match_manifest_and_scope():
    manifest = json.loads((ROOT / "datasets/beverages/manifest.json").read_text())
    assert manifest["scope"] == "beverages_first_pass"
    assert {r["country_code"] for r in manifest["workbooks"]} == {"ar", "co", "pe", "mx"}
    assert sum(r["requests"] for r in manifest["workbooks"]) == 356
    assert sum(r["locations"] for r in manifest["workbooks"]) == 8
    for record in manifest["workbooks"]:
        path = ROOT / record["path"]
        assert path.stat().st_size == record["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
        workbook = load_workbook(path, read_only=True, data_only=False)
        assert workbook.sheetnames == ["summary", "items", "ssb_candidates", "review", "comparison",
                                       "stores", "locations", "coverage", "query_yield", "data_dictionary"]
        for sheet, count in record["sheet_rows"].items():
            assert workbook[sheet].max_row - 1 == count
        header = next(workbook["items"].iter_rows(values_only=True))
        assert {"volume_per_unit_ml", "total_volume_ml", "sugar_g_per_100ml", "abv_pct",
                "beverage_flags", "product_information"}.issubset(header)
        candidate_header = next(workbook["ssb_candidates"].iter_rows(values_only=True))
        assert "ssb_candidate_status" in candidate_header
        workbook.close()


def test_shared_description_pilot_is_not_observation_evidence():
    manifest = json.loads((ROOT / "datasets/beverages/manifest.json").read_text())
    record = manifest["product_information_pilot"]
    path = ROOT / record["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert all(row["detail_scope"] == "product" for row in rows)
    assert sum(row["detail_status"] == "captured_product_page" for row in rows) == 3
    assert sum(row["detail_status"] == "truncated" for row in rows) == 1
    assert all(row["ssr_product_information"] for row in rows)
    assert record["verified_observation_joins"] == 0


def test_published_coverage_audit_matches_all_four_workbooks():
    manifest = json.loads((ROOT / "datasets/beverages/manifest.json").read_text())
    record = manifest["coverage_audit"]
    path = ROOT / record["path"]
    assert path.stat().st_size == record["bytes"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
    report = json.loads(path.read_text())
    assert report["total_locations"] == 8
    assert report["total_requests"] == 356
    assert report["catalog_completeness"] == "unknown"
    countries = {c["country_code"]: c for c in report["countries"]}
    assert set(countries) == {"ar", "co", "pe", "mx"}
    for workbook in manifest["workbooks"]:
        country = countries[workbook["country_code"]]
        assert country["raw_observations"] == workbook["raw_observations"]
        assert country["ssb_candidate_observations"] == workbook["ssb_candidate_observations"]
        assert sum(z["observations"] for z in country["locations"]) == workbook["raw_observations"]
        assert len(country["locations"]) == workbook["locations"]
        evidence = next(p for p in report["provenance"] if p["country_code"] == workbook["country_code"])
        assert evidence["provenance_sha256"] == workbook["provenance"]["sha256"]
