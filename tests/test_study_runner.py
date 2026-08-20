import gzip
import json
from hashlib import sha256
from pathlib import Path

import pytest

from rappi_co import study
from rappi_co.study import _complete_source, plan_country, run_country


def test_dry_plan_reports_request_budget():
    plan = plan_country("pe")
    assert plan["currency"] == "PEN"
    assert len(plan["addresses"]) == 2
    assert len(plan["queries"]) == 30
    assert plan["requests"] == 60
    assert plan["protocol_status"] == "full"
    assert plan["full_protocol"] is True


def test_dry_plan_accepts_one_address_and_one_term():
    plan = plan_country("mx", ["centro-bellas-artes"], ["cigarrillos"])
    assert plan["requests"] == 1
    assert plan["queries"] == ["cigarrillos"]
    assert plan["protocol_status"] == "partial"
    assert plan["full_protocol"] is False


def test_dry_plan_rejects_duplicate_address():
    with pytest.raises(ValueError, match="duplicate"):
        plan_country("mx", ["centro-bellas-artes", "centro-bellas-artes"])


def test_complete_source_requires_exact_query_manifest(tmp_path):
    items = tmp_path / "search_items_20260101_000000.csv"
    stores = tmp_path / "search_stores_20260101_000000.csv"
    raw = tmp_path / "search_raw_20260101_000000"
    items.write_text("store_id,product_id\n1,1\n", encoding="utf-8")
    stores.write_text("store_id\n1\n", encoding="utf-8")
    raw.mkdir()
    with gzip.open(raw / "cigarrillos.json.gz", "wt", encoding="utf-8") as handle:
        json.dump({"stores": []}, handle)
    manifest = {
        "complete": True, "country_code": "mx", "address": "centro-bellas-artes",
        "queries": ["cigarrillos"], "items": items.name, "stores": stores.name,
        "raw_directory": raw.name, "request_count": 1,
        "n_items": 1, "n_stores": 1,
        "term_results": [{"query": "cigarrillos", "new_items": 0}],
    }
    (tmp_path / "search_manifest_20260101_000000.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    assert _complete_source(
        tmp_path, "mx", "centro-bellas-artes", ["cigarrillos"]) == items
    with pytest.raises(FileNotFoundError, match="matches the expected 2 queries"):
        _complete_source(
            tmp_path, "mx", "centro-bellas-artes", ["vapeador", "cigarrillos"])


def test_complete_source_rejects_empty_or_malformed_raw_archive(tmp_path):
    items = tmp_path / "search_items_20260101_000000.csv"
    stores = tmp_path / "search_stores_20260101_000000.csv"
    raw = tmp_path / "search_raw_20260101_000000"
    items.write_text("store_id,product_id\n1,1\n", encoding="utf-8")
    stores.write_text("store_id\n1\n", encoding="utf-8")
    raw.mkdir()
    manifest = {
        "complete": True, "country_code": "mx", "address": "centro-bellas-artes",
        "queries": ["cigarrillos"], "request_count": 1,
        "n_items": 1, "n_stores": 1,
        "term_results": [{"query": "cigarrillos", "new_items": 0,
                          "raw_file": "001_cigarrillos.json.gz"}],
        "items": items.name, "stores": stores.name, "raw_directory": raw.name,
    }
    manifest_path = tmp_path / "search_manifest_20260101_000000.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="no complete"):
        _complete_source(tmp_path, "mx", "centro-bellas-artes", ["cigarrillos"])

    with gzip.open(raw / "001_cigarrillos.json.gz", "wt", encoding="utf-8") as handle:
        json.dump({"error": "challenge"}, handle)
    with pytest.raises(FileNotFoundError, match="no complete"):
        _complete_source(tmp_path, "mx", "centro-bellas-artes", ["cigarrillos"])


def test_complete_source_rejects_raw_archive_symlink(tmp_path):
    items = tmp_path / "search_items_20260101_000000.csv"
    stores = tmp_path / "search_stores_20260101_000000.csv"
    raw = tmp_path / "search_raw_20260101_000000"
    external = tmp_path / "external_response.json.gz"
    items.write_text("store_id,product_id\n1,1\n", encoding="utf-8")
    stores.write_text("store_id\n1\n", encoding="utf-8")
    raw.mkdir()
    with gzip.open(external, "wt", encoding="utf-8") as handle:
        json.dump({"stores": []}, handle)
    (raw / "001_cigarrillos.json.gz").symlink_to(external)
    manifest = {
        "complete": True, "country_code": "mx", "address": "centro-bellas-artes",
        "queries": ["cigarrillos"], "request_count": 1,
        "n_items": 1, "n_stores": 1,
        "term_results": [{"query": "cigarrillos", "new_items": 0,
                          "raw_file": "001_cigarrillos.json.gz"}],
        "items": items.name, "stores": stores.name, "raw_directory": raw.name,
    }
    (tmp_path / "search_manifest_20260101_000000.json").write_text(
        json.dumps(manifest), encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="no complete"):
        _complete_source(tmp_path, "mx", "centro-bellas-artes", ["cigarrillos"])


def test_complete_source_rejects_same_directory_member_symlink(tmp_path):
    actual = tmp_path / "search_items_20251231_235959.csv"
    expected = tmp_path / "search_items_20260101_000000.csv"
    stores = tmp_path / "search_stores_20260101_000000.csv"
    raw = tmp_path / "search_raw_20260101_000000"
    actual.write_text("store_id,product_id\n1,1\n", encoding="utf-8")
    expected.symlink_to(actual)
    stores.write_text("store_id\n1\n", encoding="utf-8")
    raw.mkdir()
    with gzip.open(raw / "001_cigarrillos.json.gz", "wt", encoding="utf-8") as handle:
        json.dump({"stores": []}, handle)
    manifest = {
        "complete": True, "country_code": "mx", "address": "centro-bellas-artes",
        "queries": ["cigarrillos"], "request_count": 1,
        "n_items": 1, "n_stores": 1,
        "term_results": [{"query": "cigarrillos", "new_items": 0,
                          "raw_file": "001_cigarrillos.json.gz"}],
        "items": expected.name, "stores": stores.name, "raw_directory": raw.name,
    }
    (tmp_path / "search_manifest_20260101_000000.json").write_text(
        json.dumps(manifest), encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="no complete"):
        _complete_source(tmp_path, "mx", "centro-bellas-artes", ["cigarrillos"])


@pytest.mark.parametrize(
    "items_text,n_items",
    [
        ("store_id,product_id\n1,1\n", 2),
        ("wrong_id,product_id\n1,1\n", 1),
    ],
)
def test_complete_source_rejects_collection_csv_mismatch(tmp_path, items_text, n_items):
    items = tmp_path / "search_items_20260101_000000.csv"
    stores = tmp_path / "search_stores_20260101_000000.csv"
    raw = tmp_path / "search_raw_20260101_000000"
    items.write_text(items_text, encoding="utf-8")
    stores.write_text("store_id\n1\n", encoding="utf-8")
    raw.mkdir()
    with gzip.open(raw / "001_cigarrillos.json.gz", "wt", encoding="utf-8") as handle:
        json.dump({"stores": []}, handle)
    manifest = {
        "complete": True, "country_code": "mx", "address": "centro-bellas-artes",
        "queries": ["cigarrillos"], "request_count": 1,
        "n_items": n_items, "n_stores": 1,
        "term_results": [{"query": "cigarrillos", "new_items": 0,
                          "raw_file": "001_cigarrillos.json.gz"}],
        "items": items.name, "stores": stores.name, "raw_directory": raw.name,
    }
    (tmp_path / "search_manifest_20260101_000000.json").write_text(
        json.dumps(manifest), encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="no complete"):
        _complete_source(tmp_path, "mx", "centro-bellas-artes", ["cigarrillos"])


def test_complete_source_skips_non_object_manifest_and_uses_older_valid(tmp_path):
    items = tmp_path / "search_items_20260101_000000.csv"
    stores = tmp_path / "search_stores_20260101_000000.csv"
    raw = tmp_path / "search_raw_20260101_000000"
    items.write_text("store_id,product_id\n1,1\n", encoding="utf-8")
    stores.write_text("store_id\n1\n", encoding="utf-8")
    raw.mkdir()
    with gzip.open(raw / "001_cigarrillos.json.gz", "wt", encoding="utf-8") as handle:
        json.dump({"stores": []}, handle)
    valid = {
        "complete": True, "country_code": "mx", "address": "centro-bellas-artes",
        "queries": ["cigarrillos"], "request_count": 1,
        "n_items": 1, "n_stores": 1,
        "term_results": [{"query": "cigarrillos", "new_items": 0,
                          "raw_file": "001_cigarrillos.json.gz"}],
        "items": items.name, "stores": stores.name, "raw_directory": raw.name,
    }
    (tmp_path / "search_manifest_20260101_000000.json").write_text(
        json.dumps(valid), encoding="utf-8")
    (tmp_path / "search_manifest_20260102_000000.json").write_text(
        "[]", encoding="utf-8")

    assert _complete_source(
        tmp_path, "mx", "centro-bellas-artes", ["cigarrillos"]
    ) == items


@pytest.mark.parametrize("member,value", [
    ("items", "../other/search_items_20260101_000000.csv"),
    ("stores", "/tmp/search_stores_20260101_000000.csv"),
    ("raw_directory", "../other/search_raw_20260101_000000"),
])
def test_complete_source_rejects_manifest_path_traversal(tmp_path, member, value):
    zone = tmp_path / "zone"
    other = tmp_path / "other"
    zone.mkdir()
    other.mkdir()
    (zone / "search_items_20260101_000000.csv").write_text("product_id\n1\n", encoding="utf-8")
    (zone / "search_stores_20260101_000000.csv").write_text("store_id\n1\n", encoding="utf-8")
    (zone / "search_raw_20260101_000000").mkdir()
    (other / "search_items_20260101_000000.csv").write_text("product_id\n2\n", encoding="utf-8")
    (other / "search_stores_20260101_000000.csv").write_text("store_id\n2\n", encoding="utf-8")
    (other / "search_raw_20260101_000000").mkdir()
    manifest = {
        "complete": True,
        "country_code": "mx",
        "address": "centro-bellas-artes",
        "queries": ["cigarrillos"],
        "items": "search_items_20260101_000000.csv",
        "stores": "search_stores_20260101_000000.csv",
        "raw_directory": "search_raw_20260101_000000",
    }
    manifest[member] = value
    (zone / "search_manifest_20260101_000000.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="no complete"):
        _complete_source(zone, "mx", "centro-bellas-artes", ["cigarrillos"])


def test_complete_source_requires_timestamp_paired_files(tmp_path):
    items = tmp_path / "search_items_20260102_000000.csv"
    stores = tmp_path / "search_stores_20260101_000000.csv"
    raw = tmp_path / "search_raw_20260101_000000"
    items.write_text("product_id\n1\n", encoding="utf-8")
    stores.write_text("store_id\n1\n", encoding="utf-8")
    raw.mkdir()
    manifest = {
        "complete": True,
        "country_code": "mx",
        "address": "centro-bellas-artes",
        "queries": ["cigarrillos"],
        "items": items.name,
        "stores": stores.name,
        "raw_directory": raw.name,
    }
    (tmp_path / "search_manifest_20260101_000000.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="no complete"):
        _complete_source(tmp_path, "mx", "centro-bellas-artes", ["cigarrillos"])


def _saved_source(data_root: Path, country: str, slug: str, timestamp: str) -> Path:
    directory = data_root / country / "raw" / slug
    directory.mkdir(parents=True)
    source = directory / f"search_items_{timestamp}.csv"
    source.write_text(
        "store_id,product_id,name\n0001,0002,Marlboro Rojo 20 Und\n",
        encoding="utf-8-sig",
    )
    (directory / f"search_manifest_{timestamp}.json").write_text(
        json.dumps({"complete": True}), encoding="utf-8",
    )
    return source


def _fake_pipeline(monkeypatch, data_root: Path, country: str, sources: dict[str, Path]):
    classification_paths = []
    export_calls = []

    monkeypatch.setattr(
        study,
        "_complete_source",
        lambda directory, selected_country, address, queries: sources[address],
    )

    def fake_classify(source, out, country=None):
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "store_id,product_id,primary_class,product_type,confidence,method,rationale,flags\n"
            "0001,0002,tobacco,cigarette,high,test,test,\n",
            encoding="utf-8-sig",
        )
        classification_paths.append(path)
        return str(path)

    def fake_export(selected_country, addresses, data_root, sources,
                    classification_paths, out_dir=None, run_token=None):
        export_calls.append({
            "addresses": addresses,
            "out_dir": out_dir,
            "classification_paths": classification_paths,
        })
        destination = (Path(out_dir) if out_dir else
                       Path(data_root) / selected_country / "processed" / "combined")
        destination.mkdir(parents=True, exist_ok=True)
        timestamp = run_token
        items = destination / f"tobacco_items_{timestamp}.csv"
        stores = destination / f"tobacco_stores_{timestamp}.csv"
        locations = destination / f"locations_{timestamp}.csv"
        workbook = destination / f"tobacco_master_{timestamp}.xlsx"
        item_rows = "".join(f"{slug},p{i}\n" for i, slug in enumerate(addresses, 1))
        items.write_text("zone_slug,product_id\n" + item_rows, encoding="utf-8-sig")
        stores.write_text("zone_slug,store_id\n" + item_rows, encoding="utf-8-sig")
        locations.write_text(
            "zone_slug\n" + "".join(f"{slug}\n" for slug in addresses),
            encoding="utf-8-sig",
        )
        workbook.write_bytes(b"study workbook")
        return {
            "items_csv": str(items),
            "stores_csv": str(stores),
            "locations_csv": str(locations),
            "xlsx": str(workbook),
            "n_observations": len(addresses),
            "n_store_observations": len(addresses),
        }

    monkeypatch.setattr(study, "run_classify", fake_classify)
    monkeypatch.setattr(study, "run_export", fake_export)
    return classification_paths, export_calls


def test_partial_run_isolates_derived_outputs_and_marks_manifest(tmp_path, monkeypatch):
    slug = "centro-bellas-artes"
    source = _saved_source(tmp_path, "mx", slug, "20260101_000001")
    classification_paths, export_calls = _fake_pipeline(
        monkeypatch, tmp_path, "mx", {slug: source})

    result = run_country(
        "mx", addresses=[slug], terms=["cigarrillos"], skip_collect=True,
        data_root=tmp_path,
    )

    assert result["protocol_status"] == "partial"
    assert result["full_protocol"] is False
    assert len(classification_paths) == 1
    diagnostic_root = tmp_path / "mx" / "processed" / "diagnostic"
    assert classification_paths[0].is_relative_to(diagnostic_root)
    assert export_calls[0]["out_dir"] is not None
    assert Path(export_calls[0]["out_dir"]).is_relative_to(diagnostic_root)
    assert not (tmp_path / "mx" / "processed" / slug / "classifications.csv").exists()

    manifest_path = Path(result["deliverable"]["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["protocol_status"] == "partial"
    assert manifest["full_protocol"] is False
    assert manifest["queries"] == ["cigarrillos"]
    assert manifest["locations"] == [slug]
    assert manifest["counts"]["source_rows"] == 1
    assert manifest["counts"]["classification_rows"] == 1
    source_record = manifest["inputs"]["sources"][slug]["items"]
    assert manifest["schema_version"] == 2
    assert manifest["path_base"] == "data_root"
    assert source_record["data_root_relative_path"] == (
        "mx/raw/centro-bellas-artes/search_items_20260101_000001.csv")
    assert "path" not in source_record
    assert not Path(source_record["data_root_relative_path"]).is_absolute()
    assert ".." not in Path(source_record["data_root_relative_path"]).parts
    assert source_record["sha256"] == sha256(source.read_bytes()).hexdigest()


def test_full_run_writes_manifest_with_exact_inputs_and_hashes(tmp_path, monkeypatch):
    slugs = ["centro-bellas-artes", "coyoacan-perisur"]
    sources = {
        slug: _saved_source(tmp_path, "mx", slug, f"20260101_00000{i}")
        for i, slug in enumerate(slugs, 1)
    }
    classification_paths, export_calls = _fake_pipeline(
        monkeypatch, tmp_path, "mx", sources)

    result = run_country("mx", skip_collect=True, data_root=tmp_path)

    assert result["protocol_status"] == "full"
    assert result["full_protocol"] is True
    assert export_calls[0]["out_dir"] is None
    assert all(path.parent == tmp_path / "mx" / "processed" / slug
               for path, slug in zip(classification_paths, slugs))
    assert all(path.name.startswith("classifications_") for path in classification_paths)
    assert all(path.name != "classifications.csv" for path in classification_paths)

    manifest = json.loads(
        Path(result["deliverable"]["manifest"]).read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == 2
    assert manifest["path_base"] == "data_root"
    assert manifest["protocol_status"] == "full"
    assert manifest["full_protocol"] is True
    assert manifest["queries"] == plan_country("mx")["queries"]
    assert manifest["locations"] == slugs
    assert manifest["counts"] == {
        "source_rows": 2,
        "classification_rows": 2,
        "tobacco_observations": 2,
        "store_location_observations": 2,
        "locations": 2,
    }
    records = [
        record
        for source_record in manifest["inputs"]["sources"].values()
        for record in source_record.values()
    ]
    records.extend(manifest["inputs"]["classifications"].values())
    records.extend(manifest["outputs"].values())
    for output in records:
        assert "path" not in output
        relative = Path(output["data_root_relative_path"])
        assert not relative.is_absolute()
        assert ".." not in relative.parts
        path = tmp_path / relative
        assert output["sha256"] == sha256(path.read_bytes()).hexdigest()


def test_processed_manifest_file_record_rejects_paths_outside_data_root(tmp_path):
    outside = tmp_path.parent / "outside-study-artifact.csv"
    outside.write_text("id\n1\n", encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="inside data_root"):
            study._file_record(outside, tmp_path, rows=True)
    finally:
        outside.unlink()
