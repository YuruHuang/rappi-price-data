import hashlib
import json

from openpyxl import Workbook

from rappi_co.release_update import _build_country


def _record(path):
    return {
        "data_root_relative_path": path.name,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _csv(path, headers, rows):
    path.write_text(
        ",".join(headers) + "\n" + "\n".join(",".join(row[column] for column in headers) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_country_creates_and_validates_a_new_release(tmp_path):
    tobacco_root, beverage_root = tmp_path / "tobacco", tmp_path / "beverages"
    tobacco_root.mkdir()
    beverage_root.mkdir()
    tobacco_book = tobacco_root / "tobacco.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "items"
    tobacco_headers = ["country_code", "zone_slug", "store_id", "product_id", "name", "scrape_timestamp"]
    sheet.append(tobacco_headers)
    sheet.append(["ar", "zone-a", "store-a", "product-a", "Tobacco item", "20261017_120000"])
    workbook.save(tobacco_book)
    audit_headers = ["country_code", "zone_slug", "store_id", "product_id", "name", "beverage_category", "scrape_timestamp"]
    audit_rows = [
        {"country_code": "ar", "zone_slug": "zone-a", "store_id": "store-a", "product_id": "product-b", "name": "Drink", "beverage_category": "ssb", "scrape_timestamp": "20261017_120000"},
        {"country_code": "ar", "zone_slug": "zone-a", "store_id": "store-a", "product_id": "product-c", "name": "Water", "beverage_category": "water", "scrape_timestamp": "20261017_120000"},
        {"country_code": "ar", "zone_slug": "zone-a", "store_id": "store-a", "product_id": "product-d", "name": "Beer", "beverage_category": "alcohol", "scrape_timestamp": "20261017_120000"},
    ]
    audit, candidates = beverage_root / "audit.csv", beverage_root / "candidates.csv"
    _csv(audit, audit_headers, audit_rows)
    _csv(candidates, audit_headers, [audit_rows[0]])
    tobacco_manifest = tobacco_root / "manifest.json"
    tobacco_manifest.write_text(json.dumps({"country_code": "ar", "outputs": {"xlsx": _record(tobacco_book)}}), encoding="utf-8")
    beverage_manifest = beverage_root / "manifest.json"
    beverage_manifest.write_text(json.dumps({"complete": True, "plan": {"country_code": "ar"}, "outputs": {
        "audit_csv": _record(audit), "ssb_candidates_csv": _record(candidates),
    }}), encoding="utf-8")
    destination = tmp_path / "out"
    destination.mkdir()

    result = _build_country("ar", tobacco_manifest, tobacco_root, beverage_manifest, beverage_root, destination)

    assert result["rows"] == {"tobacco": 1, "ssb_candidates": 1, "water": 1, "alcohol": 1}
    assert (destination / "argentina.xlsx").is_file()
