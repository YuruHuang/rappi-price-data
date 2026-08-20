"""Search+breadth union plumbing: store merge, per-address attribution, source preference."""
import csv

import rappi_co.collect.merge_stores as ms
import rappi_co.collect.union_zones as uz
import rappi_co.export.tobacco_deliverable as ex


def _write_stores(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ms.STORE_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def test_merge_stores_dedups_and_unions_zones(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "ROOT", tmp_path)
    _write_stores(tmp_path / "data" / "raw" / "zoneA" / "stores_a.csv", [
        {"store_id": "S1", "slug": "s1", "name": "Store 1", "url": "u1",
         "store_types": '["market"]', "discovery_zones": '["zoneA"]'},
        {"store_id": "S2", "slug": "s2", "name": "Store 2", "url": "u2",
         "store_types": '["market"]', "discovery_zones": '["zoneA"]'},
    ])
    _write_stores(tmp_path / "data" / "raw" / "zoneB" / "stores_b.csv", [
        {"store_id": "S1", "slug": "s1", "name": "Store 1", "url": "u1",
         "store_types": '["licores"]', "discovery_zones": '["zoneB"]'},
        {"store_id": "S3", "slug": "s3", "name": "Store 3", "url": "u3",
         "store_types": '["market"]', "discovery_zones": '["zoneB"]'},
    ])
    out = ms.merge_stores(["zoneA", "zoneB"], out_dir=tmp_path / "out")
    by_id = {r["store_id"]: r for r in csv.DictReader(open(out, encoding="utf-8-sig"))}

    assert set(by_id) == {"S1", "S2", "S3"}                                   # deduped by store_id
    assert set(ms._parse_list(by_id["S1"]["discovery_zones"])) == {"zoneA", "zoneB"}  # zones unioned
    assert set(ms._parse_list(by_id["S1"]["store_types"])) == {"market", "licores"}
    assert ms._parse_list(by_id["S2"]["discovery_zones"]) == ["zoneA"]


def test_zone_store_ids_filters_by_discovery_zone(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "ROOT", tmp_path)
    _write_stores(tmp_path / "data" / "raw" / "zoneA" / "stores_a.csv", [
        {"store_id": "S1", "slug": "s1", "name": "n", "url": "u", "discovery_zones": '["zoneA"]'},
    ])
    _write_stores(tmp_path / "data" / "raw" / "zoneB" / "stores_b.csv", [
        {"store_id": "S1", "slug": "s1", "name": "n", "url": "u", "discovery_zones": '["zoneB"]'},
        {"store_id": "S3", "slug": "s3", "name": "n", "url": "u", "discovery_zones": '["zoneB"]'},
    ])
    out = ms.merge_stores(["zoneA", "zoneB"], out_dir=tmp_path / "out")

    # A store reachable from both addresses is attributed to both; a B-only store never to A.
    assert uz._zone_store_ids(out, "zoneA") == {"S1"}
    assert uz._zone_store_ids(out, "zoneB") == {"S1", "S3"}


def test_menu_source_prefers_union_then_search(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "ROOT", tmp_path)
    raw = tmp_path / "data" / "raw" / "z"
    raw.mkdir(parents=True)
    (raw / "search_items_20260101_000000.csv").write_text("x\n")
    assert ex._menu_source_for("z").endswith("search_items_20260101_000000.csv")

    (raw / "menu_items_unified_20260101_010000.csv").write_text("x\n")
    assert ex._menu_source_for("z").endswith("menu_items_unified_20260101_010000.csv")
