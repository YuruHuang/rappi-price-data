"""Beverage-only collections must finish with the clean country product layout."""
import hashlib
import json
from pathlib import Path
import shutil

import httpx
from openpyxl import load_workbook
import pytest

from rappi_co import run as country_run
from rappi_co.collect import search as collector
from rappi_co.export.beverage_workbook import export_saved_run, SHEETS
from rappi_co.export.country_product_workbooks import DISPLAY, FIELD_SETS, SHEET_ACCENTS


def _collect(tmp_path, monkeypatch, *, empty=False, terms="agua,gaseosa,cerveza,diet"):
    def fake_search(term, lat, lng, **kwargs):
        if empty:
            return {"stores": []}
        product_id, name = {
            "agua": ("00001", "Agua natural 500 ml"),
            "gaseosa": ("9007199254740993123", "=Gaseosa original 500 ml"),
            "cerveza": ("00003", "Cerveza lager 330 ml"),
            "diet": ("00004", "Gaseosa sin azúcar 500 ml"),
        }[term]
        return {"stores": [{"store_id": "00007", "store_type": "market",
                            "store_name": "Fixture shop", "products": [{
            "product_id": product_id, "name": name, "price": 100, "real_price": 120,
            "is_available": True, "in_stock": True, "quantity": 500,
            "unit_type": "ml", "alcoholic_beverage": term == "cerveza",
        }]}]}

    monkeypatch.setattr(collector, "search", fake_search)
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("unexpected live request"))
    out = tmp_path / "run"
    assert country_run.main([
        "--country", "co", "--scope", "beverages", "--terms", terms,
        "--out", str(out), "--collect", "--min-delay", "0", "--max-delay", "0",
    ]) == 0
    return out


@pytest.mark.parametrize("empty", [False, True])
def test_real_beverage_only_pipeline_writes_three_clean_tabs(tmp_path, monkeypatch, empty):
    out = _collect(tmp_path, monkeypatch, empty=empty)
    manifest = json.loads((out / "manifest.json").read_text())
    book_path = out / "country_products/co_beverages.xlsx"
    book = load_workbook(book_path, data_only=False)
    try:
        assert book.sheetnames == list(SHEETS)
        for name in SHEETS:
            sheet = book[name]
            assert [cell.value for cell in sheet[1]] == [DISPLAY[field] for field in FIELD_SETS[name]]
            assert sheet.max_row == (1 if empty else 3)
            assert sheet.freeze_panes == "B2"
            assert sheet.sheet_properties.tabColor.rgb == SHEET_ACCENTS[name]
            assert sheet.auto_filter.ref
            assert sheet['A1'].font.bold
            assert sheet.column_dimensions['A'].width == 40
            for index, field in enumerate(FIELD_SETS[name], 1):
                if field == "attributes_json":
                    assert sheet.column_dimensions[sheet.cell(1, index).column_letter].hidden
            assert not any(cell.data_type in {"f", "e"} for row in sheet for cell in row)
        if not empty:
            headers = [cell.value for cell in book['SSBs'][1]]
            values = dict(zip(headers, [cell.value for cell in book['SSBs'][2]]))
            assert "Gaseosa original" in values['Product name']
            assert values['SSB candidate status'] == 'sweetening_unconfirmed'
            assert values['Price'] == 100
            assert isinstance(values['Price'], (int, float))
            assert values[DISPLAY['product_id']] == '9007199254740993123'
            assert values[DISPLAY['store_id']] == '00007'
            assert values['Sugar (g/100 mL)'] is None
    finally:
        book.close()
    assert manifest['workbook']['sha256'] == hashlib.sha256(book_path.read_bytes()).hexdigest()
    assert manifest['workbook_export']['rows'] == dict.fromkeys(SHEETS, 0 if empty else 2)
    assert book_path.with_suffix('.manifest.json').is_file()
    diagnostic = Path(manifest['result']['deliverable']['xlsx'])
    original = load_workbook(diagnostic, read_only=True)
    try:
        assert 'review' in original.sheetnames and 'summary' in original.sheetnames
    finally:
        original.close()


def test_saved_run_conversion_works_after_moving_package_without_collecting(tmp_path, monkeypatch):
    out = _collect(tmp_path, monkeypatch)
    moved = tmp_path / 'moved'
    shutil.copytree(out, moved)
    shutil.rmtree(out)
    monkeypatch.setattr(collector, 'search', lambda *a, **k: pytest.fail('offline export contacted Rappi'))
    result = export_saved_run(moved)
    assert result['rows'] == dict.fromkeys(SHEETS, 2)
    converted = moved / 'country_products/co_beverages_clean.xlsx'
    assert converted.is_file()
    assert (moved / 'country_products/co_beverages.xlsx').is_file()
    with pytest.raises(FileExistsError, match='new workbook filename'):
        export_saved_run(moved)


def test_no_results_for_one_category_still_has_all_three_tabs(tmp_path, monkeypatch):
    out = _collect(tmp_path, monkeypatch, terms='agua')
    result = json.loads((out / 'manifest.json').read_text())['workbook_export']
    assert result['rows'] == {'SSBs': 0, 'Water': 2, 'Alcohol': 0}


def test_saved_export_rejects_changed_source_before_writing(tmp_path, monkeypatch):
    out = _collect(tmp_path, monkeypatch)
    wrapper = json.loads((out / 'manifest.json').read_text())
    audit = Path(wrapper['result']['deliverable']['audit_csv'])
    audit.write_bytes(audit.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='hash differs'):
        export_saved_run(out)
    assert not (out / 'country_products/co_beverages_clean.xlsx').exists()


def test_saved_export_rejects_candidate_not_matching_audit_even_with_valid_hash(tmp_path, monkeypatch):
    import csv
    out = _collect(tmp_path, monkeypatch)
    wrapper = json.loads((out / 'manifest.json').read_text())
    manifest_path = Path(wrapper['result']['deliverable']['manifest'])
    manifest = json.loads(manifest_path.read_text())
    candidates = Path(wrapper['result']['deliverable']['ssb_candidates_csv'])
    with candidates.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        fields, rows = reader.fieldnames, list(reader)
    rows[0]['price_local'] = '99999'
    with candidates.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    manifest['outputs']['ssb_candidates_csv'].update(
        bytes=candidates.stat().st_size, sha256=hashlib.sha256(candidates.read_bytes()).hexdigest())
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='content differs'):
        export_saved_run(out)
    assert not (out / 'country_products/co_beverages_clean.xlsx').exists()
