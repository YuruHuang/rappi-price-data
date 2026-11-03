import hashlib
import json

from openpyxl import Workbook
import pytest

from rappi_co import beverages, release_update, study
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


def _custom_locations(tmp_path):
    path = tmp_path / "locations.csv"
    path.write_text(
        "country_code,slug,lat,lng,address,district,city\n"
        "co,study-a,6.25,-75.56,Public landmark,Study district,Medellin\n",
        encoding="utf-8",
    )
    return path


def test_selected_country_release_propagates_terms_and_preserves_input(tmp_path, monkeypatch):
    path = _custom_locations(tmp_path)
    out = tmp_path / "release"
    calls = []

    def fake_run(code, **kwargs):
        calls.append((code, kwargs))
        return {"deliverable": {"manifest": str(tmp_path / "source.json")}}

    monkeypatch.setattr(study, "run_country", fake_run)
    monkeypatch.setattr(beverages, "run_country", fake_run)
    monkeypatch.setattr(release_update, "_build_country", lambda code, *args: {"country_code": code})

    result = release_update.collect_and_build(
        out, 0, 0, countries=["co"], locations_file=path,
        tobacco_terms=["cigarrillos"], beverage_terms=["agua"],
    )

    assert [code for code, _ in calls] == ["co", "co"]
    assert calls[0][1]["terms"] == ["cigarrillos"]
    assert calls[1][1]["terms"] == ["agua"]
    assert all(kwargs["locations_file"] == path for _, kwargs in calls)
    assert result["selection"]["location_counts"] == {"co": 1}
    assert result["selection"]["plans"]["tobacco"][0]["addresses"][0]["city"] == "Medellin"
    assert (out / "inputs" / "locations.csv").read_bytes() == path.read_bytes()
    assert result["input_snapshot"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert [item["country_code"] for item in result["countries"]] == ["co"]
    assert not (out / "update_state.json").exists()


def test_missing_requested_country_fails_before_output_or_collection(tmp_path, monkeypatch):
    path = _custom_locations(tmp_path)
    out = tmp_path / "release"
    monkeypatch.setattr(study, "run_country", lambda *a, **k: pytest.fail("collection started"))

    with pytest.raises(ValueError, match="no delivery points"):
        release_update.collect_and_build(out, 0, 0, countries=["co", "pe"], locations_file=path)

    assert not out.exists()


def test_resume_rejects_changed_configuration_and_snapshot(tmp_path, monkeypatch):
    path = _custom_locations(tmp_path)
    config_root = tmp_path / "project"
    (config_root / "config").mkdir(parents=True)
    configuration = config_root / "config" / "classification.yml"
    configuration.write_text("rule: original\n", encoding="utf-8")
    monkeypatch.setattr(release_update, "ROOT", config_root)
    out = tmp_path / "release"

    def interrupt(*args, **kwargs):
        raise RuntimeError("interrupted")

    monkeypatch.setattr(study, "run_country", interrupt)
    with pytest.raises(RuntimeError, match="interrupted"):
        release_update.collect_and_build(out, 0, 0, countries=["co"], locations_file=path)

    monkeypatch.setattr(study, "run_country", lambda *a, **k: pytest.fail("collection resumed"))
    configuration.write_text("rule: changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="resume plan differs"):
        release_update.collect_and_build(out, 0, 0, resume=True, countries=["co"], locations_file=path)

    configuration.write_text("rule: original\n", encoding="utf-8")
    (out / "inputs" / "locations.csv").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot"):
        release_update.collect_and_build(out, 0, 0, resume=True, countries=["co"], locations_file=path)
