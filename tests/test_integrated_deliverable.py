import csv
import json
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from rappi_co.export.integrated_deliverable import (
    COUNTRIES, GROUPS, Inputs, Overflow, canonical_row, collection_date,
    export_integrated, prepare, sha256,
)


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def digest(path, root, rows=None):
    result = {"path": str(path.relative_to(root)), "bytes": path.stat().st_size, "sha256": sha256(path)}
    if rows is not None:
        result["rows"] = rows
    return result


@pytest.fixture
def sources(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    tobacco_manifest = {"prepared_date": "2026-08-20", "source_collection_date": "2026-08-16", "files": []}
    beverage_manifest = {"workbooks": []}
    for code, (country, currency) in COUNTRIES.items():
        base = {"country_code": code, "country": country, "currency": currency, "zone_slug": "zone",
                "store_id": "00012", "product_id": "00123", "master_product_id": "000456",
                "ean": "00012345678901234567", "name": "=Literal product name", "brand": "Example",
                "price_local": "0", "original_price_local": "12.50", "address": "Sample address",
                "district": "District", "latitude": "1.25", "longitude": "-3.5"}
        tobacco = {**base, "scrape_timestamp": "20260816_171214", "volume_ml": "3.5",
                   "pack_count": "20", "unit_price_local": "1.25", "study_category": "cigarettes",
                   "nicotine_pct": "0", "quantity": "1.0", "unusual_tobacco_field": "keep me"}
        tp = root / "datasets" / (country.lower() + ".xlsx")
        tp.parent.mkdir(parents=True, exist_ok=True)
        tw = Workbook()
        ws = tw.active
        ws.title = "items"
        ws.append(list(tobacco))
        ws.append(list(tobacco.values()))
        # Explicit text, including formula-looking names and long EAN identifiers.
        for cell in ws[2]:
            if isinstance(cell.value, str):
                cell.data_type = "s"
        loc = {k: tobacco[k] for k in ("country_code", "country", "currency", "zone_slug", "address", "district", "latitude", "longitude")}
        ls = tw.create_sheet("locations")
        ls.append(list(loc)); ls.append(list(loc.values()))
        dd = tw.create_sheet("data_dictionary")
        dd.append(["sheet", "column", "definition"])
        dd.append(["items", "volume_ml", "Original tobacco volume definition."])
        tw.save(tp)
        tobacco_manifest["files"].append({**digest(tp, root), "country_code": code, "observations": 1})
        rows = []
        for index, category in enumerate(["water", "review", "alcohol", "non_ssb", "review", "excluded"]):
            rows.append({**base, "product_id": f"{123 + index:05}", "scrape_timestamp": "20260910_044028",
                         "beverage_category": category, "ssb_candidate_status": "", "beverage_flags": "[\"review_flag\"]" if category == "review" else "[]",
                         "volume_per_unit_ml": "500", "pack_count": "1", "total_volume_ml": "500",
                         "price_per_liter_local": "0", "sugar_g_per_100ml": "", "abv_pct": "0" if category == "non_ssb" else "",
                         "volume_ml": "99", "source_product_json": '{"literal": "=1+1"}',
                         "unusual_beverage_field": "keep this too"})
        run = "20260910_120000_000001"
        generated = root / "data/beverages" / code / "processed" / run
        candidates = [{**rows[1], "ssb_candidate_status": "sweetening_unconfirmed"}]
        bl = [{"country_code": code, "currency": currency, "slug": "zone", "lat": "1.25", "lng": "-3.5", "address": "Sample address", "district": "District"}]
        outputs = {}
        for kind, records in [("audit_csv", rows), ("ssb_candidates_csv", candidates), ("locations_csv", bl)]:
            path = generated / (kind + ".csv")
            write_csv(path, records)
            outputs[kind] = {**digest(path, root, len(records)), "data_root_relative_path": str(path.relative_to(root / "data/beverages"))}
        bp = root / "datasets/beverages" / (country.lower() + ".xlsx")
        bp.parent.mkdir(parents=True, exist_ok=True)
        bw = Workbook(); bw.active.title = "data_dictionary"
        bw.active.append(["column", "definition"])
        bw.active.append(["volume_per_unit_ml", "Supported beverage per-unit volume."])
        bw.save(bp)
        prov = {"complete": True, "run_id": run, "plan": {"country_code": code, "addresses": [{"slug": "zone"}]}, "outputs": outputs}
        pp = root / "datasets/beverages" / f"provenance_{code}.json"
        pp.write_text(json.dumps(prov))
        beverage_manifest["workbooks"].append({**digest(bp, root), "country_code": code, "locations": 1,
                                               "raw_observations": 6, "ssb_candidate_observations": 1,
                                               "water_observations": 1, "alcohol_observations": 1,
                                               "review_observations": 2, "comparison_observations": 1,
                                               "excluded_observations": 1, "confirmed_ssb_observations": 0,
                                               "provenance": digest(pp, root)})
    (root / "datasets/manifest.json").write_text(json.dumps(tobacco_manifest))
    (root / "datasets/beverages/manifest.json").write_text(json.dumps(beverage_manifest))
    return root


def rows(workbook, sheet):
    it = workbook[sheet].iter_rows(values_only=True)
    headers = next(it)
    return [dict(zip(headers, values)) for values in it]


def mutate_csv(root, kind, mutate, code="ar"):
    pp = root / "datasets/beverages" / f"provenance_{code}.json"
    prov = json.loads(pp.read_text())
    path = root / "data/beverages" / prov["outputs"][kind]["data_root_relative_path"]
    with path.open(encoding="utf-8-sig", newline="") as handle:
        data = list(csv.DictReader(handle))
    mutate(data)
    write_csv(path, data)
    prov["outputs"][kind].update(bytes=path.stat().st_size, sha256=sha256(path))
    pp.write_text(json.dumps(prov))
    bm_path = root / "datasets/beverages/manifest.json"
    bm = json.loads(bm_path.read_text())
    next(x for x in bm["workbooks"] if x["country_code"] == code)["provenance"] = digest(pp, root)
    bm_path.write_text(json.dumps(bm))


def test_full_export_conserves_rows_types_dates_sources_and_disjoint_views(sources, tmp_path):
    before = {p: sha256(p) for p in sources.rglob("*") if p.is_file()}
    out = tmp_path / "integrated"
    manifest = export_integrated(sources, out)
    assert manifest["observations"] == 28
    assert manifest["overflow_cells"] == 0
    assert manifest["network_requests"] == 0
    assert manifest["collection_waves"] == {"tobacco": ["2026-08-16"], "beverages": ["2026-09-10"]}
    assert before == {p: sha256(p) for p in before}
    master = load_workbook(out / "all_countries.xlsx", read_only=True, data_only=False)
    try:
        for code, (country, _) in COUNTRIES.items():
            records = rows(master, country)
            assert len(records) == 7
            assert len({r["record_id"] for r in records}) == 7
            # Same original observation key appears in both waves and survives twice.
            repeated = [r for r in records if r["product_id"] == "00123"]
            assert len(repeated) == 2
            assert {r["source_collection_date"] for r in repeated} == {"2026-08-16", "2026-09-10"}
            assert all(r["store_id"] == "00012" and r["ean"] == "00012345678901234567" for r in records)
            assert all(r["price_local"] == 0 and isinstance(r["price_local"], (float, int)) for r in records)
            assert all(r["sugar_g_per_100ml"] is None for r in records)
            tobacco = next(r for r in records if r["source_dataset"] == "tobacco")
            assert tobacco["tobacco_volume_ml"] == 3.5 and tobacco["volume_per_unit_ml"] is None
            assert tobacco["tobacco_pack_count"] == 20 and tobacco["pack_count"] is None
            assert tobacco["tobacco_unusual_tobacco_field"] == "keep me"
            assert tobacco["tobacco_nicotine_pct"] == 0
            beverage = next(r for r in records if r["reporting_group"] == "Water")
            assert beverage["volume_ml"] == "99" and beverage["volume_per_unit_ml"] == 500
            assert beverage["unusual_beverage_field"] == "keep this too"
            candidate = next(r for r in records if r["reporting_group"] == "SSB_candidates")
            assert candidate["beverage_category"] == "review" and candidate["ssb_candidate_status"] is None
            assert candidate["candidate_view_status"] == "sweetening_unconfirmed"
            assert candidate["beverage_flags"] == '["review_flag"]'
            cw = load_workbook(out / (country.lower() + ".xlsx"), read_only=True, data_only=False)
            try:
                country_records = [r for group in GROUPS for r in rows(cw, group)]
                assert len(country_records) == 7
                assert {r["record_id"] for r in country_records} == {r["record_id"] for r in records}
                assert all(len(rows(cw, group)) == 1 for group in GROUPS)
                assert not any(cell.data_type == "f" for row in cw["Tobacco"].iter_rows() for cell in row)
            finally:
                cw.close()
        assert sum(r["observations"] for r in rows(master, "Coverage")) == 28
    finally:
        master.close()
    for entry in manifest["files"]:
        assert sha256(out / entry["path"]) == entry["sha256"]
    with pytest.raises(FileExistsError):
        export_integrated(sources, out)


@pytest.mark.parametrize("field,value,message", [
    ("country_code", "mx", "Country/currency"),
    ("currency", "USD", "Country/currency"),
    ("zone_slug", "wrong-zone", "Unknown source location"),
    ("latitude", "9", "Location latitude"),
    ("scrape_timestamp", "yesterday", "collection timestamp"),
    ("price_local", "NaN", "Nonfinite numeric"),
])
def test_invalid_source_semantics_fail_before_output(sources, tmp_path, field, value, message):
    mutate_csv(sources, "audit_csv", lambda data: data[0].update({field: value}))
    out = tmp_path / "must_not_exist"
    with pytest.raises(ValueError, match=message):
        export_integrated(sources, out)
    assert not out.exists()


def test_source_hash_mismatch_is_not_silently_reaccepted(sources, tmp_path):
    path = next((sources / "data/beverages/ar").rglob("audit_csv.csv"))
    with path.open("a") as handle:
        handle.write("\n")
    with pytest.raises(ValueError, match="Source hash/size mismatch"):
        export_integrated(sources, tmp_path / "out")


def test_candidate_overlap_is_rejected(sources):
    def change(data):
        data[0]["product_id"] = "00123"  # water row, incompatible with candidate routing
        data[0]["beverage_category"] = "water"
        data[0]["beverage_flags"] = "[]"
    mutate_csv(sources, "ssb_candidates_csv", change)
    with pytest.raises(ValueError, match="Candidate overlaps incompatible category"):
        prepare(sources)


def test_candidate_source_values_must_match_audit(sources):
    mutate_csv(sources, "ssb_candidates_csv", lambda data: data[0].update(price_local="999"))
    with pytest.raises(ValueError, match="Candidate/audit source mismatch"):
        prepare(sources)


def test_duplicate_source_observation_fails(sources):
    mutate_csv(sources, "audit_csv", lambda data: data[5].update(product_id=data[4]["product_id"]))
    with pytest.raises(ValueError, match="Duplicate observation"):
        prepare(sources)


def test_row_count_mismatch_fails(sources):
    mutate_csv(sources, "audit_csv", lambda data: data.pop())
    with pytest.raises(ValueError, match="Source observation count mismatch"):
        prepare(sources)


def test_record_id_includes_release_and_preserves_tobacco_numeric_semantics():
    raw = {"country_code": "ar", "zone_slug": "z/one", "store_id": "0001", "product_id": "0002",
           "scrape_timestamp": "20260816_171214", "pack_count": "20", "volume_ml": "", "nicotine_pct": "0"}
    a = canonical_row(raw, "tobacco", "release-one", "items.xlsx", 2, {})
    b = canonical_row(raw, "tobacco", "release-two", "items.xlsx", 2, {})
    assert a["record_id"] != b["record_id"]
    assert "z%2Fone" in a["record_id"]
    assert a["tobacco_volume_ml"] is None and a["tobacco_nicotine_pct"] == 0
    assert "pack_count" not in a and a["tobacco_pack_count"] == 20
    raw["store_id"] = 1
    with pytest.raises(ValueError, match="not stored as text"):
        canonical_row(raw, "tobacco", "r", "p", 2, {})


def test_overflow_preserves_full_text_and_hash_without_silent_truncation(tmp_path):
    path = tmp_path / "overflow.csv"
    overflow = Overflow(path)
    original = "🧪" * 16384  # exceeds Excel UTF-16 limit despite fewer Python characters
    ref = overflow.value(original, "record", "evidence")
    invalid = overflow.value("before\x00after", "record2", "evidence")
    assert "overflow_000001" in ref and "overflow_000002" in invalid
    assert overflow.value("=1+1", "record", "name") == "=1+1"
    overflow.close()
    with path.open(newline="") as handle:
        entries = list(csv.DictReader(handle))
    assert entries[0]["full_text"] == original
    assert entries[1]["full_text"] == "before\x00after"
    import hashlib
    assert entries[0]["sha256"] == hashlib.sha256(original.encode()).hexdigest()


def test_input_immutability_guard_detects_late_change(tmp_path):
    p = tmp_path / "input"
    p.write_text("original")
    inputs = Inputs(tmp_path)
    inputs.add("input", "test")
    p.write_text("modified")
    with pytest.raises(ValueError, match="Source changed"):
        inputs.assert_unchanged()


def test_collection_date_is_recorded_day_not_export_day():
    assert collection_date("20260816_235959") == "2026-08-16"
    assert collection_date("20260910_000000") == "2026-09-10"
