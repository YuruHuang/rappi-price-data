import json
from pathlib import Path

import pytest
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from rappi_co.export.country_product_workbooks import (
    COUNTRIES,
    DISPLAY,
    EXPECTED_COUNTS,
    FIELD_SETS,
    HIDDEN_FIELDS,
    NUMERIC,
    SHEETS,
    SHEET_HIDDEN_FIELDS,
    SOURCE_SHEETS,
    TECHNICAL_FIELDS,
    TECHNICAL_LABELS,
    TEXT_IDS,
    CountryExcel,
    _brand_matrix,
    _discount_number,
    _same,
    export_country_workbooks,
    sha256,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "datasets/country_products"


def test_schema_is_category_specific_and_excludes_canceled_detail_fields():
    forbidden = {
        "product_information", "ingredients_text", "nutrition_text", "detail_status",
        "detail_url", "detail_retrieved_at", "detail_evidence_path", "detail_evidence_sha256",
        "tobacco_primary_class", "tobacco_confidence", "tobacco_method",
        "tobacco_rationale", "tobacco_flags", "beverage_category",
        "classification_reason", "beverage_flags", "beverage_evidence_json",
    }
    assert tuple(FIELD_SETS) == SHEETS[1:]
    assert not forbidden.intersection(set().union(*map(set, FIELD_SETS.values())))
    assert {"tobacco_brand_market_scope", "tobacco_pack_count", "tobacco_puff_count",
            "tobacco_nicotine_pct", "tobacco_unit_price_local"} \
        <= set(FIELD_SETS["Tobacco products"])
    assert {"sugar_g_per_100ml", "sugar_g_per_serving", "serving_volume_ml", "abv_pct",
            "alcoholic_beverage", "candidate_view_status"} \
        <= set(FIELD_SETS["SSBs"])
    assert "abv_pct" in FIELD_SETS["Alcohol"]
    assert "sugar_status" in FIELD_SETS["Alcohol"]
    assert "abv_pct" not in FIELD_SETS["Water"]
    assert "brand" not in FIELD_SETS["SSBs"]
    assert DISPLAY["candidate_view_status"] == "SSB candidate status"
    assert "stock" not in NUMERIC
    for sheet in ("SSBs", "Water", "Alcohol"):
        assert {"stock", "is_available_raw", "in_stock_raw",
                "is_possible_stockout_raw", "thumbnail_url"} <= set(FIELD_SETS[sheet])
    assert "thumbnail_url" in FIELD_SETS["Tobacco products"]
    for sheet, fields in FIELD_SETS.items():
        assert len(fields) == len(set(fields))
        assert len(fields) == len({DISPLAY[field] for field in fields})
        hidden = [field in HIDDEN_FIELDS or field in SHEET_HIDDEN_FIELDS.get(sheet, set())
                  for field in fields]
        first_hidden = hidden.index(True)
        assert not any(hidden[:first_hidden])
        assert all(hidden[first_hidden:])


def test_real_category_layout_serializes_the_intended_visible_columns(tmp_path):
    expected_visible = {
        "Tobacco products": (
            "name", "brand", "tobacco_brand_market_scope", "tobacco_study_category",
            "tobacco_product_type", "price_local", "original_price_local", "currency",
            "tobacco_discount_pct", "tobacco_quantity", "tobacco_pack_count",
            "tobacco_volume_ml", "tobacco_puff_count", "tobacco_nicotine_mg_per_ml",
            "tobacco_nicotine_mg_per_pouch", "tobacco_nicotine_pct",
            "tobacco_unit_price_local", "tobacco_unit_price_unit", "tobacco_stock",
            "tobacco_age_restriction", "tobacco_has_antismoking", "tobacco_has_menthol",
            "availability", "source_collection_date", "zone_slug", "store_name", "store_id",
            "product_id", "record_id",
        ),
        "SSBs": (
            "name", "price_local", "original_price_local", "currency",
            "candidate_view_status", "sugar_status", "sugar_g_per_100ml",
            "sugar_g_per_serving", "serving_volume_ml", "abv_pct", "alcoholic_beverage",
            "volume_per_unit_ml", "pack_count", "total_volume_ml",
            "price_per_liter_local", "presentation", "beverage_subcategory", "discount_pct",
            "availability", "source_collection_date", "zone_slug", "store_name", "store_id",
            "product_id", "record_id",
        ),
        "Water": (
            "name", "price_local", "original_price_local", "currency",
            "volume_per_unit_ml", "pack_count", "total_volume_ml",
            "price_per_liter_local", "presentation", "beverage_subcategory", "discount_pct",
            "availability", "source_collection_date", "zone_slug", "store_name", "store_id",
            "product_id", "record_id",
        ),
        "Alcohol": (
            "name", "price_local", "original_price_local", "currency", "abv_pct",
            "volume_per_unit_ml", "pack_count", "total_volume_ml",
            "price_per_liter_local", "presentation", "beverage_subcategory", "discount_pct",
            "age_restriction", "identification_required", "availability",
            "source_collection_date", "zone_slug", "store_name", "store_id", "product_id",
            "record_id",
        ),
    }
    path = tmp_path / "visibility.xlsx"
    excel = CountryExcel(path, "Argentina")
    excel.table("Technical specifications", TECHNICAL_FIELDS, TECHNICAL_LABELS)
    excel.append("Technical specifications", {"section": "Overview", "item": "Test"})
    for sheet, fields in FIELD_SETS.items():
        excel.table(sheet, fields)
        excel.append(sheet, {"name": "Example"})
    excel.save()

    workbook = load_workbook(path, read_only=False, data_only=False)
    try:
        for sheet, fields in FIELD_SETS.items():
            worksheet = workbook[sheet]
            visible = []
            first_hidden = len(fields) + 1
            for index, field in enumerate(fields, 1):
                dimension = worksheet.column_dimensions[get_column_letter(index)]
                if dimension.hidden:
                    first_hidden = min(first_hidden, index)
                    assert dimension.outlineLevel == 1
                else:
                    assert first_hidden == len(fields) + 1
                    visible.append(field)
            assert tuple(visible) == expected_visible[sheet]
            assert first_hidden == len(expected_visible[sheet]) + 1
    finally:
        workbook.close()


def test_brand_matrix_has_country_market_and_international_examples_in_all_cells():
    integrated = json.loads((ROOT / "datasets/integrated/manifest.json").read_text())
    matrix, _ = _brand_matrix(ROOT, integrated)
    assert set(matrix) == {
        (code, family) for code in COUNTRIES for family in ("water", "ssb", "alcohol")
    }
    for row in matrix.values():
        assert int(row["local_observation_count"]) > 0
        assert int(row["international_observation_count"]) > 0
        assert row["local_brand"] and row["international_brand"]


def test_discount_fraction_conversion_is_numeric_precise_and_bounded():
    assert _discount_number("0.20459999") == pytest.approx(0.20459999)
    for value in ("not-a-number", "-0.01", "1.01", "NaN", "Infinity"):
        with pytest.raises(ValueError):
            _discount_number(value)


def test_formula_looking_strings_remain_literal_text(tmp_path):
    excel = CountryExcel(tmp_path / "literal.xlsx")
    excel.table("Technical specifications", TECHNICAL_FIELDS, TECHNICAL_LABELS)
    excel.append("Technical specifications", {"section": "Test", "description": '=1+1'})
    for sheet in SHEETS[1:]:
        excel.table(sheet, ("name",))
        excel.append(sheet, {"name": "+literal"})
    excel.save()
    workbook = load_workbook(tmp_path / "literal.xlsx", data_only=False)
    try:
        assert workbook["Technical specifications"]["C2"].value == "=1+1"
        assert workbook["Technical specifications"]["C2"].data_type == "s"
        for sheet in SHEETS[1:]:
            assert workbook[sheet]["A2"].value == "+literal"
            assert workbook[sheet]["A2"].data_type == "s"
    finally:
        workbook.close()


def test_workbook_uses_a_restrained_analyst_friendly_layout(tmp_path):
    excel = CountryExcel(tmp_path / "styled.xlsx", "Argentina")
    excel.table("Technical specifications", TECHNICAL_FIELDS, TECHNICAL_LABELS)
    excel.append("Technical specifications", {
        "section": "Overview",
        "item": "Purpose",
        "description": "A concise note for the analyst.",
    })
    for sheet in SHEETS[1:]:
        excel.table(sheet, ("name", "price_local", "currency", "discount_pct", "abv_pct",
                            "source_url"))
        excel.append(sheet, {
            "name": "Example product",
            "price_local": 1234.5,
            "currency": "COP",
            "discount_pct": "0.20459999",
            "abv_pct": 5,
            "source_url": "https://example.com/product",
        })
    excel.save()

    workbook = load_workbook(tmp_path / "styled.xlsx", data_only=False)
    try:
        assert workbook.properties.title == "Rappi product listings — Argentina"
        specifications = workbook["Technical specifications"]
        assert specifications.freeze_panes == "C2"
        assert specifications.sheet_view.showGridLines is False
        assert specifications.sheet_view.zoomScale == 90
        assert specifications.sheet_properties.tabColor.rgb == "FF44546A"
        assert specifications["A1"].font.bold
        assert specifications["A1"].font.color.rgb == "FFFFFFFF"
        assert specifications["A1"].fill.fgColor.rgb == "FF44546A"
        assert specifications["A1"].border.bottom.style == "medium"
        assert specifications["A2"].font.bold
        assert specifications["A2"].fill.fgColor.rgb == "FFD9E2F3"
        assert specifications["C2"].alignment.wrap_text
        assert specifications.column_dimensions["A"].width == 20
        assert specifications.column_dimensions["C"].width == 68

        tobacco = workbook["Tobacco products"]
        assert tobacco.freeze_panes == "B2"
        assert tobacco.sheet_view.showGridLines
        assert tobacco.sheet_properties.tabColor.rgb == "FF806000"
        assert tobacco["A1"].fill.fgColor.rgb == "FF806000"
        assert tobacco["A2"].fill.fill_type is None
        assert tobacco["A2"].font.name == "Calibri"
        assert tobacco["A2"].font.sz == 10
        assert tobacco["B2"].number_format == "#,##0.##"
        assert tobacco["C2"].alignment.horizontal == "center"
        assert tobacco["D2"].value == pytest.approx(0.20459999)
        assert tobacco["D2"].number_format == "0.0%"
        assert tobacco["E2"].number_format == '0.0"%"'
        assert tobacco.column_dimensions["F"].hidden
        assert tobacco.column_dimensions["F"].outlineLevel == 1
        assert tobacco.auto_filter.ref == "A1:F2"
    finally:
        workbook.close()


def test_export_refuses_an_existing_destination(tmp_path):
    with pytest.raises(FileExistsError, match="Destination must be new"):
        export_country_workbooks(tmp_path)


def test_final_country_workbooks_match_the_frozen_sources():
    manifest_path = OUTPUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert manifest["status"] == "final_country_category_workbooks"
    assert manifest["scope"] == "frozen_target_observations_four_countries_five_sheets"
    assert manifest["network_requests"] == 0
    assert manifest["sheet_order"] == list(SHEETS)
    assert manifest["product_rows"] == 68398
    assert manifest["excluded_integrated_observations"] == 27290
    assert {path.name for path in OUTPUT.glob("*.xlsx")} == {
        meta["filename"] for meta in COUNTRIES.values()
    }
    for entry in [*manifest["files"], manifest["documentation"]]:
        path = OUTPUT / entry["path"]
        assert path.stat().st_size == entry["bytes"]
        assert sha256(path) == entry["sha256"]
    for entry in manifest["inputs"]:
        path = ROOT / entry["path"]
        assert path.stat().st_size == entry["bytes"]
        assert sha256(path) == entry["sha256"]

    integrated = json.loads((ROOT / "datasets/integrated/manifest.json").read_text())
    entries = {entry["country_code"]: entry for entry in manifest["files"]}
    total = 0
    total_sugar_values = 0
    total_candidate_statuses = 0
    total_alcohol_abv = 0
    for code, meta in COUNTRIES.items():
        output_path = OUTPUT / meta["filename"]
        source_path = ROOT / "datasets/integrated" / meta["filename"]
        entry = entries[code]
        assert entry["product_rows"] == sum(EXPECTED_COUNTS[code].values())
        assert entry["reporting_groups"] == EXPECTED_COUNTS[code]
        source_entry = next(item for item in integrated["files"]
                            if item["path"] == meta["filename"])
        assert entry["source_sha256"] == source_entry["sha256"]
        output = load_workbook(output_path, read_only=True, data_only=False)
        source = load_workbook(source_path, read_only=True, data_only=False)
        try:
            assert output.sheetnames == list(SHEETS)
            technical_rows = list(output["Technical specifications"].iter_rows(values_only=True))
            assert technical_rows[0] == TECHNICAL_LABELS
            assert len(technical_rows) < 180
            technical = {(row[0], row[1]): row for row in technical_rows[1:]}
            assert "Screening cohort" in technical[("Category summary", "SSBs")][2]
            assert "unconfirmed sweetening status" in \
                technical[("Category summary", "SSBs")][2]
            assert "unknown, not that the product contains no sugar" in \
                technical[("Reading notes", "Sugar")][2]
            assert "Product-detail pages are not included" in \
                technical[("Reading notes", "Product titles")][2]
            assert "not estimates of national availability" in \
                technical[("Reading notes", "Geographic scope")][2]
            assert "country-market" in technical[("Brand checks", "Water")][2]
            assert "international example" in technical[("Brand checks", "Alcohol")][2]
            assert "full beverage discovery audit" in technical[("Brand checks", "SSBs")][2]
            assert "outside the SSB worksheet" in technical[("Brand checks", "SSBs")][2]
            assert "not verified inventory counts" in \
                technical[("Reading notes", "Availability and stock")][2]
            assert ("Shared fields", "Product name") in technical
            assert technical[("Shared fields", "Alcohol by volume (%)")][4] == \
                "Number (% ABV)"

            seen = set()
            for output_sheet, source_sheet in SOURCE_SHEETS.items():
                out_rows = output[output_sheet].iter_rows(values_only=False)
                source_rows = source[source_sheet].iter_rows(values_only=False)
                out_headers = [cell.value for cell in next(out_rows)]
                source_headers = [cell.value for cell in next(source_rows)]
                source_index = {field: index for index, field in enumerate(source_headers)}
                assert out_headers == [DISPLAY[field] for field in FIELD_SETS[output_sheet]]
                count = 0
                for out_cells, source_cells in zip(out_rows, source_rows, strict=True):
                    count += 1
                    assert not any(cell.data_type in {"f", "e"} for cell in out_cells)
                    for field, cell in zip(FIELD_SETS[output_sheet], out_cells):
                        source_value = source_cells[source_index[field]].value
                        assert _same(cell.value, source_value), (code, output_sheet, count, field)
                        if field in TEXT_IDS and cell.value not in (None, ""):
                            assert isinstance(cell.value, str)
                    record_id = source_cells[source_index["record_id"]].value
                    assert record_id not in seen
                    seen.add(record_id)
                    if output_sheet == "SSBs":
                        candidate = out_cells[FIELD_SETS[output_sheet].index(
                            "candidate_view_status")].value
                        total_candidate_statuses += bool(candidate)
                        for field in ("sugar_g_per_100ml", "sugar_g_per_serving",
                                      "serving_volume_ml"):
                            total_sugar_values += bool(out_cells[
                                FIELD_SETS[output_sheet].index(field)].value)
                    elif output_sheet == "Alcohol":
                        total_alcohol_abv += bool(out_cells[
                            FIELD_SETS[output_sheet].index("abv_pct")].value)
                assert count == EXPECTED_COUNTS[code][output_sheet]
                assert entry["sheet_rows"][output_sheet] == count
            assert len(seen) == entry["product_rows"]
            total += len(seen)
        finally:
            output.close()
            source.close()
    assert total == 68398
    assert total_candidate_statuses == 23229
    assert total_sugar_values == 0
    assert total_alcohol_abv == 24666
