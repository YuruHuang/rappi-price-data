import csv
from pathlib import Path

import pytest
from openpyxl import load_workbook

import rappi_co.export.study_deliverable as study_deliverable
from rappi_co.export.study_deliverable import (
    DATA_DICTIONARY,
    ITEM_COLS,
    LOCATION_COLS,
    STORE_COLS,
    _attribute_puff_count,
    _configured_brand,
    _heated_carton_total,
    _heated_single_pack_total,
    _pack_format_total,
    _reviewed_cigarette_carton_total,
    _single_category_brand_variants,
    run_export,
)
from rappi_co.configs import load_study_profile


def _write(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _minimal_export_inputs(root: Path) -> str:
    slug = "centro-galerias-pacifico"
    raw = root / "ar" / "raw" / slug / "search_items_20260101_000000.csv"
    classified = root / "ar" / "processed" / slug / "classifications.csv"
    _write(raw, [{
        "store_id": "s1", "product_id": "p1", "name": "Marlboro Rojo 20 Und",
        "brand": "Marlboro", "store_type": "market", "store_name": "Store",
        "parent_store_type": "retail", "price_local": "1000",
        "original_price_local": "", "unit_price_unit": "und", "pack_count": "20",
        "volume_ml": "", "availability": "in_stock", "source_term": "cigarrillos",
        "source_url": "unified-search", "scrape_timestamp": "2026-01-01T00:00:00Z",
    }])
    _write(classified, [{
        "store_id": "s1", "product_id": "p1", "primary_class": "tobacco",
        "product_type": "cigarette", "confidence": "high", "method": "keyword_strong",
        "rationale": "brand", "flags": "",
    }])
    return slug


def test_export_uses_one_microsecond_token_and_refuses_existing_targets(tmp_path):
    slug = _minimal_export_inputs(tmp_path)
    token = "20260101_010203_123456"

    result = run_export(
        "ar", addresses=[slug], data_root=tmp_path, run_token=token)

    expected_names = {
        "items_csv": f"tobacco_items_{token}.csv",
        "stores_csv": f"tobacco_stores_{token}.csv",
        "locations_csv": f"locations_{token}.csv",
        "xlsx": f"tobacco_master_{token}.xlsx",
    }
    original_bytes = {}
    for key, expected in expected_names.items():
        path = Path(result[key])
        assert path.name == expected
        original_bytes[key] = path.read_bytes()

    with pytest.raises(FileExistsError, match="targets already exist"):
        run_export("ar", addresses=[slug], data_root=tmp_path, run_token=token)

    for key in expected_names:
        assert Path(result[key]).read_bytes() == original_bytes[key]
    destination = Path(result["items_csv"]).parent
    assert not [path for path in destination.iterdir() if path.name.startswith(".")]


def test_export_preserves_custom_location_city_and_coordinates(tmp_path, monkeypatch):
    slug = _minimal_export_inputs(tmp_path)
    locations_file = tmp_path / "delivery_points.csv"
    locations_file.write_text("locations test fixture\n", encoding="utf-8")
    profile = load_study_profile("ar", Path("config/study"))
    profile["zones"] = [{
        "slug": slug, "lat": -31.42, "lng": -64.18,
        "address": "Public landmark", "district": "Centro", "city": "Cordoba",
    }]
    calls = []

    def custom_profile(country, config_dir, locations_file=None):
        calls.append((country, locations_file))
        return profile

    monkeypatch.setattr(study_deliverable, "load_study_profile", custom_profile)
    result = run_export("ar", addresses=[slug], data_root=tmp_path,
                        locations_file=locations_file)
    for artifact in ("items_csv", "locations_csv"):
        with open(result[artifact], encoding="utf-8-sig", newline="") as handle:
            row = next(csv.DictReader(handle))
        assert row["city"] == "Cordoba"
        assert row["address"] == "Public landmark"
        assert float(row["latitude"]) == -31.42
        assert float(row["longitude"]) == -64.18
    assert calls == [("ar", locations_file)]


@pytest.mark.parametrize("has_irrelevant_listing", [False, True])
def test_export_zero_target_products_preserves_schema_and_all_custom_locations(
        tmp_path, has_irrelevant_listing):
    locations_file = tmp_path / "delivery_points.csv"
    locations_file.write_text(
        "country_code,slug,lat,lng,address,district,city\n"
        "co,point-a,4.60,-74.08,Public landmark A,Centro,Bogota\n"
        "co,point-b,4.67,-74.05,Public landmark B,North,Bogota\n"
        "co,point-c,6.25,-75.56,Public landmark C,Centro,Medellin\n",
        encoding="utf-8",
    )
    sources, classifications = {}, {}
    for slug in ("point-a", "point-b", "point-c"):
        raw = tmp_path / "co" / "raw" / slug / "search_items_20260101_000000.csv"
        classified = tmp_path / "co" / "processed" / slug / "classifications.csv"
        raw.parent.mkdir(parents=True)
        classified.parent.mkdir(parents=True)
        with raw.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["store_id", "product_id", "name"])
            writer.writeheader()
            if has_irrelevant_listing:
                writer.writerow({"store_id": "s1", "product_id": "p1", "name": "Notebook"})
        with classified.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "store_id", "product_id", *study_deliverable.CLASSIFICATION_COLS])
            writer.writeheader()
            if has_irrelevant_listing:
                writer.writerow({"store_id": "s1", "product_id": "p1",
                                 "primary_class": "non_tobacco", "product_type": "unknown",
                                 "confidence": "high", "method": "test", "rationale": "irrelevant"})
        sources[slug] = raw
        classifications[slug] = classified

    result = run_export(
        "co", data_root=tmp_path, sources=sources,
        classification_paths=classifications, locations_file=locations_file,
        run_token="20260101_010203_123456",
    )
    assert result["n_observations"] == 0
    assert result["n_store_observations"] == 0
    for artifact, columns in (("items_csv", ITEM_COLS), ("stores_csv", STORE_COLS)):
        with open(result[artifact], encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            assert reader.fieldnames == columns
            assert list(reader) == []
    with open(result["locations_csv"], encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == LOCATION_COLS
        locations = list(reader)
    assert [row["zone_slug"] for row in locations] == ["point-a", "point-b", "point-c"]
    assert [row["city"] for row in locations] == ["Bogota", "Bogota", "Medellin"]
    assert all(row["n_tobacco_observations"] == "0" for row in locations)
    book = load_workbook(result["xlsx"], read_only=True)
    assert book.sheetnames == ["items", "stores", "locations", "summary", "data_dictionary"]
    assert book["items"].max_row == 1
    assert book["stores"].max_row == 1
    assert book["locations"].max_row == 4
    summary = dict(book["summary"].iter_rows(min_row=2, values_only=True))
    assert summary["locations"] == 3
    assert summary["tobacco_observations"] == 0
    assert summary["store_location_observations"] == 0
    assert all(value == 0 for key, value in summary.items() if key.startswith("products_"))
    book.close()


def test_export_rolls_back_partial_finalization_and_cleans_staging(
        tmp_path, monkeypatch):
    slug = _minimal_export_inputs(tmp_path)
    token = "20260101_010203_654321"
    original_replace = Path.replace

    def fail_on_second_artifact(path, target):
        if Path(target).name == f"tobacco_stores_{token}.csv":
            raise OSError("simulated finalization failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_on_second_artifact)
    with pytest.raises(OSError, match="finalization failure"):
        run_export("ar", addresses=[slug], data_root=tmp_path, run_token=token)

    destination = tmp_path / "ar" / "processed" / slug
    assert not list(destination.glob(f"*{token}*"))
    assert not [path for path in destination.iterdir() if path.name.startswith(".")]


def test_export_rejects_unsafe_run_token_before_writing(tmp_path):
    slug = _minimal_export_inputs(tmp_path)
    with pytest.raises(ValueError, match="run_token"):
        run_export(
            "ar", addresses=[slug], data_root=tmp_path,
            run_token="../../overwrite",
        )


def test_country_export_uses_local_currency_and_scope(tmp_path):
    slug = "centro-galerias-pacifico"
    raw = tmp_path / "ar" / "raw" / slug / "search_items_20260101_000000.csv"
    classified = tmp_path / "ar" / "processed" / slug / "classifications.csv"
    _write(raw, [{
        "store_id": "s1", "product_id": "p1", "name": "Dolchester Blue 20 Und",
        "brand": "", "store_type": "market",
        "store_name": '=HYPERLINK("https://bad.example","click")',
        "parent_store_type": "retail", "price_local": "1000",
        "original_price_local": "1200", "unit_price_unit": "", "pack_count": "",
        "volume_ml": "", "product_type": "", "availability": "in_stock",
        "source_term": "dolchester cigarrillos", "source_url": "unified-search",
        "scrape_timestamp": "2026-01-01T00:00:00Z",
    }])
    _write(classified, [{
        "store_id": "s1", "product_id": "p1", "primary_class": "tobacco",
        "product_type": "cigarette", "confidence": "high", "method": "keyword_strong",
        "rationale": "brand", "flags": "",
    }])

    result = run_export("ar", addresses=[slug], data_root=tmp_path)
    with open(result["items_csv"], encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["currency"] == "ARS"
    assert row["price_local"] == "1000"
    assert row["discount_amount_local"] == "200"
    assert row["unit_price_local"] == "50.0"
    assert row["brand"] == "Dolchester"
    assert row["brand_market_scope"] == "local_market"
    assert row["study_category"] == "cigarettes"
    assert row["store_name"] == '=HYPERLINK("https://bad.example","click")'

    workbook = load_workbook(result["xlsx"], read_only=True)
    assert workbook.sheetnames == ["items", "stores", "locations", "summary", "data_dictionary"]
    sheet = workbook["items"]
    headers = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    store_cell = sheet.cell(row=2, column=headers.index("store_name") + 1)
    assert store_cell.value == '\'=HYPERLINK("https://bad.example","click")'
    assert store_cell.data_type == "s"
    workbook.close()

    workbook = load_workbook(result["xlsx"])
    assert workbook.active.title == "summary"
    sheet = workbook["items"]
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == sheet.dimensions
    assert not sheet.tables
    assert sheet["A1"].fill.fgColor.rgb == "00E7E6E6"
    headers = {cell.value: cell.column for cell in sheet[1]}
    assert sheet.cell(2, headers["price_local"]).number_format == "#,##0.00"
    dictionary = workbook["data_dictionary"]
    assert dictionary["C2"].alignment.wrap_text is True
    workbook.close()

    with open(result["locations_csv"], encoding="utf-8-sig", newline="") as handle:
        location = next(csv.DictReader(handle))
    assert set(location) == set(LOCATION_COLS)
    assert location["zone_slug"] == slug
    assert location["n_tobacco_observations"] == "1"


def test_export_keeps_only_study_categories_and_matches_compact_brand(tmp_path):
    slug = "centro-galerias-pacifico"
    raw = tmp_path / "ar" / "raw" / slug / "search_items_20260101_000000.csv"
    classified = tmp_path / "ar" / "processed" / slug / "classifications.csv"
    base = {
        "store_id": "s1", "brand": "", "store_type": "market", "store_name": "Store",
        "parent_store_type": "retail", "price_local": "1000",
        "original_price_local": "", "unit_price_unit": "", "pack_count": "100",
        "volume_ml": "", "availability": "in_stock", "source_term": "vapeador",
        "source_url": "unified-search", "scrape_timestamp": "2026-01-01T00:00:00Z",
    }
    _write(raw, [
        {**base, "product_id": "p1", "name": "Elfbar Strawberry Spark 40k",
         "attributes_json": '{"puffs": 30000}'},
        {**base, "product_id": "p2", "name": "Cohiba Robusto"},
        {**base, "product_id": "p3", "name": "Elfbar Strawberry",
         "attributes_json": '{"puffs": 15000}'},
    ])
    classification_base = {
        "store_id": "s1", "primary_class": "tobacco", "confidence": "high",
        "method": "keyword_strong", "rationale": "brand", "flags": "",
    }
    _write(classified, [
        {**classification_base, "product_id": "p1", "product_type": "vape_disposable"},
        {**classification_base, "product_id": "p2", "product_type": "cigar"},
        {**classification_base, "product_id": "p3", "product_type": "vape_disposable"},
    ])

    result = run_export("ar", addresses=[slug], data_root=tmp_path)
    with open(result["items_csv"], encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    by_id = {row["product_id"]: row for row in rows}
    assert by_id["p1"]["brand"] == "Elf Bar"
    assert by_id["p1"]["brand_market_scope"] == "international"
    assert by_id["p1"]["study_category"] == "electronic_cigarettes"
    assert by_id["p1"]["puff_count"] == "40000.0"
    assert by_id["p1"]["pack_count"] == ""
    assert by_id["p1"]["unit_price_local"] == ""
    assert by_id["p1"]["unit_price_unit"] == ""
    assert by_id["p3"]["puff_count"] == "15000.0"


def test_cigarette_carton_export_uses_total_stick_count(tmp_path):
    slug = "centro-galerias-pacifico"
    raw = tmp_path / "ar" / "raw" / slug / "search_items_20260101_000000.csv"
    classified = tmp_path / "ar" / "processed" / slug / "classifications.csv"
    _write(raw, [{
        "store_id": "s1", "product_id": "p1",
        "name": "Cigarrillo Cartón Pielroja 18 Und",
        "brand": "", "store_type": "market", "store_name": "Store",
        "parent_store_type": "retail", "price_local": "66785.6",
        "original_price_local": "", "unit_price_unit": "und", "pack_count": "18",
        "pack_format_raw": "10 x 18 Und", "quantity": "18", "volume_ml": "",
        "availability": "in_stock",
        "source_term": "marlboro cigarrillos", "source_url": "unified-search",
        "scrape_timestamp": "2026-01-01T00:00:00Z",
    }, {
        "store_id": "s1", "product_id": "p2",
        "name": "L&M Blue X10 Cigarrillos Cartón",
        "brand": "", "store_type": "market", "store_name": "Store",
        "parent_store_type": "retail", "price_local": "48500",
        "original_price_local": "", "unit_price_unit": "und", "pack_count": "",
        "pack_format_raw": "1 Und", "quantity": "1", "volume_ml": "",
        "availability": "in_stock",
        "source_term": "l&m cigarrillos", "source_url": "unified-search",
        "scrape_timestamp": "2026-01-01T00:00:00Z",
    }])
    _write(classified, [{
        "store_id": "s1", "product_id": "p1", "primary_class": "tobacco",
        "product_type": "cigarette", "confidence": "high", "method": "keyword_strong",
        "rationale": "brand", "flags": "",
    }, {
        "store_id": "s1", "product_id": "p2", "primary_class": "tobacco",
        "product_type": "cigarette", "confidence": "high", "method": "keyword_strong",
        "rationale": "brand", "flags": "",
    }])

    result = run_export("ar", addresses=[slug], data_root=tmp_path)
    with open(result["items_csv"], encoding="utf-8-sig", newline="") as handle:
        rows = {row["product_id"]: row for row in csv.DictReader(handle)}
    row = rows["p1"]
    assert float(row["pack_count"]) == 180
    assert float(row["unit_price_local"]) == 371.03
    assert row["unit_price_unit"] == "und"
    assert float(row["quantity"]) == 18
    assert float(rows["p2"]["pack_count"]) == 100
    assert float(rows["p2"]["unit_price_local"]) == 485


def test_explicit_pack_format_total_requires_unit_denominator():
    assert _pack_format_total("10 x 18 Und") == 180
    assert _pack_format_total("20 X 10 unds") == 200
    assert _pack_format_total("1 x 200 Und") == 200
    assert _pack_format_total("1 x 30 g") is None
    assert _reviewed_cigarette_carton_total("L&M Blue X10 Cigarrillos Cartón") == 100
    assert _reviewed_cigarette_carton_total("Marlboro X10 Cigarrillos Cartón") is None
    assert _reviewed_cigarette_carton_total(
        "L&M Cigarrillo Carton Media Blue + 18 10 Und", "7702005702417"
    ) == 100
    assert _reviewed_cigarette_carton_total(
        "L&M Cigarrillo Carton Media Blue + 18 10 Und", "wrong-ean"
    ) is None
    assert _reviewed_cigarette_carton_total(
        "Cigarrillo Cartón Lucky Strike Atomic 10´S"
    ) == 10


def test_ambiguous_inner_pack_format_needs_reviewed_carton_identity(tmp_path):
    slug = "chapinero-andino"
    raw = tmp_path / "co" / "raw" / slug / "search_items_20260101_000000.csv"
    classified = tmp_path / "co" / "processed" / slug / "classifications.csv"
    base = {
        "store_id": "s1", "brand": "", "ean": "", "store_type": "market",
        "store_name": "Store", "parent_store_type": "retail", "price_local": "39900",
        "original_price_local": "", "unit_price_unit": "und", "pack_count": "10",
        "pack_format_raw": "1 x 10 Und", "quantity": "10", "volume_ml": "",
        "availability": "in_stock", "source_term": "l&m cigarrillos",
        "source_url": "unified-search", "scrape_timestamp": "2026-01-01T00:00:00Z",
    }
    media_name = "L&M Cigarrillo Carton Media Blue + 18 10 Und"
    atomic_name = "Cigarrillo Cartón Lucky Strike Atomic 10´S"
    _write(raw, [
        {**base, "product_id": "reviewed", "name": media_name, "ean": "7702005702417"},
        {**base, "product_id": "unreviewed", "name": media_name, "ean": "wrong-ean"},
        {**base, "product_id": "generic", "name": "Generic Cigarrillo Cartón 10 Und"},
        {**base, "product_id": "atomic", "name": atomic_name, "price_local": "9200"},
    ])
    classification_base = {
        "store_id": "s1", "primary_class": "tobacco", "product_type": "cigarette",
        "confidence": "high", "method": "keyword_strong", "rationale": "brand",
        "flags": "",
    }
    _write(classified, [
        {**classification_base, "product_id": "reviewed"},
        {**classification_base, "product_id": "unreviewed"},
        {**classification_base, "product_id": "generic"},
        {**classification_base, "product_id": "atomic"},
    ])

    result = run_export("co", addresses=[slug], data_root=tmp_path)
    with open(result["items_csv"], encoding="utf-8-sig", newline="") as handle:
        rows = {row["product_id"]: row for row in csv.DictReader(handle)}
    assert float(rows["reviewed"]["pack_count"]) == 100
    assert float(rows["reviewed"]["unit_price_local"]) == 399
    assert rows["unreviewed"]["pack_count"] == ""
    assert rows["generic"]["pack_count"] == ""
    assert float(rows["atomic"]["pack_count"]) == 10
    assert float(rows["atomic"]["unit_price_local"]) == 920


def test_explicit_title_stick_count_beats_conflicting_inner_pack_metadata(tmp_path):
    slug = "centro-bellas-artes"
    raw = tmp_path / "mx" / "raw" / slug / "search_items_20260101_000000.csv"
    classified = tmp_path / "mx" / "processed" / slug / "classifications.csv"
    _write(raw, [{
        "store_id": "s1", "product_id": "2113769940",
        "name": "Marlboro Crafted Red 15s", "brand": "Marlboro",
        "store_type": "market", "store_name": "Store", "parent_store_type": "retail",
        "price_local": "66", "original_price_local": "", "unit_price_unit": "und",
        "pack_count": "20", "pack_format_raw": "1 X 20 Und", "quantity": "20",
        "volume_ml": "", "availability": "in_stock", "source_term": "marlboro cigarrillos",
        "source_url": "unified-search", "scrape_timestamp": "2026-01-01T00:00:00Z",
    }])
    _write(classified, [{
        "store_id": "s1", "product_id": "2113769940", "primary_class": "tobacco",
        "product_type": "cigarette", "confidence": "high", "method": "keyword_strong",
        "rationale": "brand", "flags": "",
    }])

    result = run_export("mx", addresses=[slug], data_root=tmp_path)
    with open(result["items_csv"], encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert float(row["pack_count"]) == 15
    assert float(row["unit_price_local"]) == 4.4


def test_attribute_puff_fallback_rejects_placeholder_and_liquids(tmp_path):
    assert _attribute_puff_count('{"puffs": 200}') is None
    assert _attribute_puff_count('{"puffs": 15000}') == 15000

    slug = "miraflores-larcomar"
    raw = tmp_path / "pe" / "raw" / slug / "search_items_20260101_000000.csv"
    classified = tmp_path / "pe" / "processed" / slug / "classifications.csv"
    base = {
        "store_id": "s1", "brand": "", "store_type": "market", "store_name": "Store",
        "parent_store_type": "retail", "price_local": "50", "original_price_local": "",
        "unit_price_unit": "", "pack_count": "", "quantity": "1", "volume_ml": "",
        "availability": "in_stock", "source_term": "vapeador",
        "source_url": "unified-search", "scrape_timestamp": "2026-01-01T00:00:00Z",
    }
    _write(raw, [
        {**base, "product_id": "title", "name": "Vape 32000 Puffs", "attributes_json": '{"puffs": 200}'},
        {**base, "product_id": "placeholder", "name": "Vape Mystery", "attributes_json": '{"puffs": 200}'},
        {**base, "product_id": "liquid", "name": "Liquido Para Vape 30ml", "attributes_json": '{"puffs": 15000}'},
        {**base, "product_id": "fallback", "name": "Vape Mystery Plus", "attributes_json": '{"puffs": 15000}'},
    ])
    classification_base = {
        "store_id": "s1", "primary_class": "tobacco", "confidence": "high",
        "method": "keyword_strong", "rationale": "vape", "flags": "",
    }
    _write(classified, [
        {**classification_base, "product_id": "title", "product_type": "vape"},
        {**classification_base, "product_id": "placeholder", "product_type": "vape"},
        {**classification_base, "product_id": "liquid", "product_type": "vape_liquid"},
        {**classification_base, "product_id": "fallback", "product_type": "vape"},
    ])

    result = run_export("pe", addresses=[slug], data_root=tmp_path)
    with open(result["items_csv"], encoding="utf-8-sig", newline="") as handle:
        rows = {row["product_id"]: row for row in csv.DictReader(handle)}
    assert rows["title"]["puff_count"] == "32000.0"
    assert rows["placeholder"]["puff_count"] == ""
    assert rows["liquid"]["puff_count"] == ""
    assert rows["fallback"]["puff_count"] == "15000.0"


def _export_single_vape_row(tmp_path, country, slug, name, product_type="vape"):
    raw = tmp_path / country / "raw" / slug / "search_items_20260101_000000.csv"
    classified = tmp_path / country / "processed" / slug / "classifications.csv"
    _write(raw, [{
        "store_id": "s1", "product_id": "p1", "name": name, "brand": "",
        "store_type": "market", "store_name": "Store", "parent_store_type": "retail",
        "price_local": "100", "original_price_local": "", "unit_price_unit": "und",
        "pack_count": "20", "quantity": "20", "volume_ml": "",
        "availability": "in_stock", "source_term": "vapeador",
        "source_url": "unified-search", "scrape_timestamp": "2026-01-01T00:00:00Z",
    }])
    _write(classified, [{
        "store_id": "s1", "product_id": "p1", "primary_class": "tobacco",
        "product_type": product_type, "confidence": "high", "method": "keyword_strong",
        "rationale": "vape", "flags": "reviewed",
    }])
    result = run_export(country, addresses=[slug], data_root=tmp_path)
    with open(result["items_csv"], encoding="utf-8-sig", newline="") as handle:
        return next(csv.DictReader(handle))


def test_mixed_nicotine_and_gift_vape_bundles_are_flagged_and_blank(tmp_path):
    # Two independent family identities joined by a bundle marker, or a two-vape gift offer in
    # any country, are shelf-price observations without component-specific fields.
    cases = [
        ("pe", "miraflores-larcomar",
         "Combo Vuse Go Arándano 5.000 Puffs+Velo Menta Fresca 4Mg"),
        ("pe", "miraflores-larcomar",
         "Combo Vuse Go 1000 Puffs+Zyn Menta 3Mg"),
        ("co", "chapinero-andino",
         "Vape 15k De Regalo + Hookalit 35k - Gum Mint"),
        ("pe", "independencia-megaplaza",
         "Vape 15k de regalo + Vape Nexa 30k Puffs"),
        ("mx", "centro-bellas-artes",
         "Vapeador 5000 puffs & Cajetilla Marlboro Cigarrillos"),
    ]
    for index, (country, slug, name) in enumerate(cases):
        row = _export_single_vape_row(tmp_path / f"positive-{index}", country, slug, name)
        assert row["flags"] == "reviewed|mixed_bundle", name
        for column in ("nicotine_mg_per_ml", "nicotine_mg_per_pouch", "nicotine_pct",
                       "puff_count", "pack_count", "unit_price_local", "unit_price_unit"):
            assert row[column] == "", (name, column)


def test_same_family_and_multi_category_brand_bundles_are_not_mixed(tmp_path):
    # Same-family pairs and titles whose only second identity is a multi-category brand
    # (Glucloud is reviewed for both pouches and vapes in Colombia) are not cross-family bundles.
    cases = [
        ("co", "chapinero-andino", "Terea Amber Cajetilla + Terea Purple Capso Cajetilla",
         "heated_tobacco"),
        ("co", "chapinero-andino",
         "Terea Cigarrillo Amber + Terea Cigarrillo Purple", "heated_tobacco"),
        ("co", "chapinero-andino", "Terea Amber + Heets Purple", "heated_tobacco"),
        ("co", "chapinero-andino", "Combo Glucloud Pod Uva 4000 Puff + Batería", "vape"),
        ("pe", "miraflores-larcomar", "Combo WAKA Pod 15k + Batería", "vape"),
        ("co", "chapinero-andino", "Zyn Menta 3 Mg + Zyn Cítrico 3 Mg Pouches", "nicotine_pouch"),
        ("co", "chapinero-andino", "Zyn Mint + Velo Menta Pouches 4mg", "nicotine_pouch"),
        ("pe", "miraflores-larcomar", "Kit Elfbar Ew9000 Grape Ice 5% 9000 Puffs", "vape"),
        ("pe", "miraflores-larcomar",
         "Cigarrillo Electrónico Vape 5000 Puffs Blueberry y Mint", "vape"),
        ("ar", "palermo-alto-palermo",
         "Combo Cigarrillo Electrónico Marlboro 5000 Puffs", "vape"),
        ("mx", "centro-bellas-artes",
         "Combo Cigarrillo Electrónico Camel 5000 Puffs", "vape"),
        ("ar", "palermo-alto-palermo",
         "Vape Camel Tobacco 5000 Puffs Blueberry y Mint", "vape"),
        ("ar", "palermo-alto-palermo",
         "Vape Marlboro 5000 Puffs Strawberry y Mint", "vape"),
        ("ar", "palermo-alto-palermo",
         "Vape Blueberry y Marlboro Tobacco Flavor", "vape"),
        ("mx", "centro-bellas-artes",
         "Vape Blueberry y Zyn Mango Flavor", "vape"),
        ("ar", "palermo-alto-palermo", "Combo Master Vape 5000 Puffs", "vape"),
        ("co", "chapinero-andino", "Vape 5000 Puffs + cargador de regalo", "vape"),
        ("co", "chapinero-andino", "Vape 5000 Puffs + llavero de regalo", "vape"),
        ("co", "chapinero-andino", "L&M Cigarrillos", "cigarette"),
        ("mx", "centro-bellas-artes", "Benson & Hedges Cigarrillos", "cigarette"),
    ]
    for index, (country, slug, name, product_type) in enumerate(cases):
        row = _export_single_vape_row(tmp_path / f"negative-{index}", country, slug, name,
                                      product_type=product_type)
        assert "mixed_bundle" not in row["flags"], name


def test_bundle_brand_variants_respect_context_and_canonical_cross_category_scope():
    co = load_study_profile("co", Path("config/study"))
    pe = load_study_profile("pe", Path("config/study"))
    co_variants = _single_category_brand_variants(co["brand_terms"])
    pe_variants = _single_category_brand_variants(pe["brand_terms"])
    assert "glucloud" not in co_variants
    assert "glu cloud" not in co_variants
    assert "waka" not in pe_variants
    assert co_variants["mijo"]["match"] == "context_required"
    assert pe_variants["velo"]["match"] == "context_required"

    artificial = [
        {"brand": "Shared", "aliases": ["Only Vape Alias"],
         "category": "electronic_cigarettes", "match": "distinctive"},
        {"brand": "Shared", "aliases": ["Only Pouch Alias"],
         "category": "nicotine_pouches", "match": "distinctive"},
    ]
    variants = _single_category_brand_variants(artificial)
    assert "shared" not in variants
    assert "only vape alias" not in variants
    assert "only pouch alias" not in variants


def test_heated_welcome_kit_keeps_category_but_not_unit_denominator(tmp_path):
    slug = "centro-bellas-artes"
    raw = tmp_path / "mx" / "raw" / slug / "search_items_20260101_000000.csv"
    classified = tmp_path / "mx" / "processed" / slug / "classifications.csv"
    _write(raw, [{
        "store_id": "s1", "product_id": "p1",
        "name": "Kit de Bienvenida Iqos Iluma One I Clásico 10 Und",
        "brand": "", "store_type": "market", "store_name": "Store",
        "parent_store_type": "retail", "price_local": "599",
        "original_price_local": "", "unit_price_unit": "und", "pack_count": "10",
        "quantity": "10", "volume_ml": "", "availability": "in_stock",
        "source_term": "iqos dispositivo tabaco calentado",
        "source_url": "unified-search", "scrape_timestamp": "2026-01-01T00:00:00Z",
    }])
    _write(classified, [{
        "store_id": "s1", "product_id": "p1", "primary_class": "tobacco",
        "product_type": "heated_tobacco", "confidence": "high",
        "method": "keyword_strong", "rationale": "heated kit",
        "flags": "study_heated_welcome_kit",
    }])

    result = run_export("mx", addresses=[slug], data_root=tmp_path)
    with open(result["items_csv"], encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["study_category"] == "heated_tobacco"
    assert row["flags"] == "study_heated_welcome_kit"
    assert row["pack_count"] == ""
    assert row["unit_price_local"] == ""
    assert row["unit_price_unit"] == ""


def test_discount_amount_is_rounded_to_two_decimals(tmp_path):
    slug = "miraflores-larcomar"
    raw = tmp_path / "pe" / "raw" / slug / "search_items_20260101_000000.csv"
    classified = tmp_path / "pe" / "processed" / slug / "classifications.csv"
    _write(raw, [{
        "store_id": "s1", "product_id": "p1", "name": "Marlboro Rojo 20 Und",
        "brand": "", "store_type": "market", "store_name": "Store",
        "parent_store_type": "retail", "price_local": "85.8",
        "original_price_local": "114.4", "unit_price_unit": "und", "pack_count": "20",
        "quantity": "20", "volume_ml": "", "availability": "in_stock",
        "source_term": "marlboro cigarrillos", "source_url": "unified-search",
        "scrape_timestamp": "2026-01-01T00:00:00Z",
    }])
    _write(classified, [{
        "store_id": "s1", "product_id": "p1", "primary_class": "tobacco",
        "product_type": "cigarette", "confidence": "high", "method": "keyword_strong",
        "rationale": "brand", "flags": "",
    }])

    result = run_export("pe", addresses=[slug], data_root=tmp_path)
    with open(result["items_csv"], encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["discount_amount_local"] == "28.6"
    assert row["discount_pct"] == "0.25"


def test_heated_cartons_are_normalized_to_sticks():
    assert _heated_carton_total("TEREA Amber Cartón x 10 Cajetillas Total") == 200
    assert _heated_carton_total("Terea Amelia Cartón X10 Cajetillas") == 200
    assert _heated_carton_total("Paquete Terea Blue Con 10 Cajetillas") == 200
    assert _heated_carton_total("Terea Amber 5 Cajetillas") == 100
    assert _heated_carton_total("10 x Carton Scarlet Iluma") == 200
    assert _heated_carton_total("10 x Carton Marlboro") is None


def test_single_heated_cajetilla_is_normalized_to_sticks():
    assert _heated_single_pack_total("Terea Cigarrillo Purple Cajetilla") == 20
    assert _heated_single_pack_total("TEREA Amber Cajetilla 20 unidades") == 20
    assert _heated_single_pack_total("Terea Amber Cajetilla + Terea Blue Cajetilla") is None
    assert _heated_single_pack_total("TEREA Amber Cartón x 10 Cajetillas") is None


def test_heated_multipack_uses_leading_bundle_count(tmp_path):
    slug = "centro-bellas-artes"
    raw = tmp_path / "mx" / "raw" / slug / "search_items_20260101_000000.csv"
    classified = tmp_path / "mx" / "processed" / slug / "classifications.csv"
    base = {
        "store_id": "s1",
        "brand": "", "store_type": "market", "store_name": "Store",
        "parent_store_type": "retail", "price_local": "267",
        "original_price_local": "", "unit_price_unit": "und", "pack_count": "20",
        "quantity": "20", "volume_ml": "", "availability": "in_stock",
        "source_term": "terea tabaco para iqos", "source_url": "unified-search",
        "scrape_timestamp": "2026-01-01T00:00:00Z",
    }
    _write(raw, [
        {**base, "product_id": "p1", "name": "3 x Terea Sienna",
         "pack_format_raw": "1 x 20 Und"},
        {**base, "product_id": "p2", "name": "Terea Amber 2 Und + Terea Blue 2 Und",
         "pack_count": "", "quantity": "1"},
        {**base, "product_id": "p3", "name": "3x Zyn Cool Mint 6mg",
         "pack_count": "3", "quantity": "3", "source_term": "zyn bolsas de nicotina"},
        {**base, "product_id": "p4", "name": "10 x Carton Scarlet Iluma",
         "pack_count": "", "quantity": "1", "pack_format_raw": "1 x 1 Und"},
        {**base, "product_id": "p5", "name": "Terea Cigarrillo Purple Cajetilla",
         "pack_format_raw": "10 x 20 Und"},
    ])
    classified_base = {
        "store_id": "s1", "primary_class": "tobacco",
        "confidence": "high", "method": "keyword_strong", "rationale": "brand", "flags": "",
    }
    _write(classified, [
        {**classified_base, "product_id": "p1", "product_type": "heated_tobacco"},
        {**classified_base, "product_id": "p2", "product_type": "heated_tobacco"},
        {**classified_base, "product_id": "p3", "product_type": "nicotine_pouch"},
        {**classified_base, "product_id": "p4", "product_type": "heated_tobacco"},
        {**classified_base, "product_id": "p5", "product_type": "heated_tobacco"},
    ])

    result = run_export("mx", addresses=[slug], data_root=tmp_path)
    with open(result["items_csv"], encoding="utf-8-sig", newline="") as handle:
        rows = {row["product_id"]: row for row in csv.DictReader(handle)}
    assert float(rows["p1"]["pack_count"]) == 60
    assert float(rows["p1"]["unit_price_local"]) == 4.45
    assert float(rows["p4"]["pack_count"]) == 200
    assert float(rows["p4"]["unit_price_local"]) == 1.34
    assert float(rows["p5"]["pack_count"]) == 20
    assert float(rows["p5"]["unit_price_local"]) == 13.35
    for product_id in ("p2", "p3"):
        assert rows[product_id]["pack_count"] == ""
        assert rows[product_id]["unit_price_local"] == ""
        assert rows[product_id]["unit_price_unit"] == ""


def test_brand_matching_is_limited_to_the_classified_category():
    root = Path(__file__).resolve().parent.parent
    profile = load_study_profile("pe", root / "config" / "study")
    assert _configured_brand(
        "Kik Stlth Pouches de Nicotina Strawberry Kiwi Ice",
        "",
        "nicotine_pouches",
        profile["brand_terms"],
    ) == ("KIK", "local_market")


def test_peru_cigarette_spelling_aliases_are_canonicalized():
    root = Path(__file__).resolve().parent.parent
    profile = load_study_profile("pe", root / "config" / "study")
    assert _configured_brand(
        "Cigarros Malboro Gold Cajetilla 20u", "", "cigarettes",
        profile["brand_terms"],
    ) == ("Marlboro", "international")
    assert _configured_brand(
        "LyM Cigarrillo Electro Fusión Cajetilla", "", "cigarettes",
        profile["brand_terms"],
    ) == ("L&M", "international")


def test_dictionary_covers_every_export_column():
    covered = {(sheet, column) for sheet, column, _ in DATA_DICTIONARY}
    assert {("items", column) for column in ITEM_COLS}.issubset(covered)
    assert {("stores", column) for column in STORE_COLS}.issubset(covered)
    assert {("locations", column) for column in LOCATION_COLS}.issubset(covered)
