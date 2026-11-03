"""Every scope uses the published country-product presentation."""
import json
from pathlib import Path
import shutil

import httpx
from openpyxl import load_workbook
import pytest

from rappi_co import run as country_run
from rappi_co.collect import search as collector
from rappi_co.export.country_product_workbooks import DISPLAY, FIELD_SETS, SHEET_ACCENTS, TECHNICAL_LABELS
from rappi_co.export.product_workbook import export_saved_run


@pytest.mark.parametrize('scope', ['tobacco', 'both'])
@pytest.mark.parametrize('empty', [False, True])
def test_collection_and_moved_saved_run_use_clean_country_layout(tmp_path, monkeypatch, scope, empty):
    calls = []

    def search(term, lat, lng, **kwargs):
        calls.append(term)
        if empty:
            return {'stores': []}
        name = {'cigarrillos': 'Marlboro Rojo 20 Und', 'agua': 'Agua natural 500 ml',
                'gaseosa': 'Gaseosa original 500 ml', 'cerveza': 'Cerveza lager 330 ml'}[term]
        return {'stores': [{'store_id': '00007', 'store_type': 'market', 'store_name': 'Fixture shop',
                            'products': [{'product_id': {'cigarrillos': '00001', 'agua': '00002',
                                                        'gaseosa': '00003', 'cerveza': '00004'}[term], 'name': name,
                                          'price': 100, 'real_price': 120, 'is_available': True,
                                          'in_stock': True, 'alcoholic_beverage': term == 'cerveza'}]}]}

    monkeypatch.setattr(collector, 'search', search)
    monkeypatch.setattr(httpx.Client, 'send', lambda *a, **k: pytest.fail('unexpected live network request'))
    locations = tmp_path / 'locations.csv'
    locations.write_text('slug,address,lat,lng,city\npoint-a,Public point A,6.25,-75.56,Medellin\n'
                         'point-b,Public point B,3.45,-76.53,\n', encoding='utf-8')
    out = tmp_path / 'run'
    args = ['--country', 'co', '--scope', scope, '--locations-file', str(locations),
            '--out', str(out), '--collect', '--min-delay', '0', '--max-delay', '0']
    if scope == 'both':
        args += ['--tobacco-terms', 'cigarrillos', '--beverage-terms', 'agua,gaseosa,cerveza']
    else:
        args += ['--terms', 'cigarrillos']
    assert country_run.main(args) == 0
    assert len(calls) == (8 if scope == 'both' else 2)
    path = out / 'country_products' / ('colombia.xlsx' if scope == 'both' else 'co_tobacco.xlsx')
    expected = ['Technical specifications', 'Tobacco products']
    if scope == 'both':
        expected += ['SSBs', 'Water', 'Alcohol']
    book = load_workbook(path, data_only=False)
    try:
        assert book.sheetnames == expected
        assert tuple(cell.value for cell in book['Technical specifications'][1]) == TECHNICAL_LABELS
        overview = {row[1].value: row[2].value for row in book['Technical specifications'] if row[0].value == 'Overview'}
        assert overview['Delivery locations'] == '2'
        assert len(overview['Collection dates'].split(', ')[0]) == 8
        for name in expected[1:]:
            sheet = book[name]
            assert [cell.value for cell in sheet[1]] == [DISPLAY[field] for field in FIELD_SETS[name]]
            assert sheet.max_row == (1 if empty else 3)
            assert sheet.freeze_panes == 'B2'
            assert sheet.sheet_properties.tabColor.rgb == SHEET_ACCENTS[name]
            assert sheet.column_dimensions['A'].width == 40
            assert sheet['A1'].font.bold
            assert not any(cell.data_type in {'f', 'e'} for row in sheet for cell in row)
        if not empty:
            sheet = book['Tobacco products']
            row = dict(zip(FIELD_SETS['Tobacco products'], [cell.value for cell in sheet[2]]))
            assert row['store_id'] == '00007'
            assert row['tobacco_study_category'] == 'cigarettes'
            assert row['price_local'] == 100
            assert row['tobacco_pack_count'] == 20
            assert sheet.cell(2, FIELD_SETS['Tobacco products'].index('tobacco_discount_pct') + 1).number_format == '0.0%'
    finally:
        book.close()
    if scope == 'tobacco':
        manifest = json.loads((out / 'manifest.json').read_text())
        assert manifest['workbook_export']['sheets'] == expected
        assert (out / 'inputs/01_locations.csv').read_bytes() == locations.read_bytes()
    moved = tmp_path / 'moved'
    shutil.copytree(out, moved)
    shutil.rmtree(out)
    calls.clear()
    result = export_saved_run(moved)
    assert len(result) == 1
    assert calls == []
    clean = moved / 'country_products' / ('co_products_clean.xlsx' if scope == 'both' else 'co_tobacco_clean.xlsx')
    assert clean.is_file() and clean.with_suffix('.manifest.json').is_file()
    with pytest.raises(FileExistsError, match='new workbook filename'):
        export_saved_run(moved)
    source = (next((moved / 'raw/tobacco').rglob('tobacco_master_*.xlsx')) if scope == 'both'
              else next((moved / 'source').rglob('tobacco_items_*.csv')))
    original_clean = clean.read_bytes()
    source.write_bytes(source.read_bytes() + b'changed')
    rejected = moved / 'country_products/rejected.xlsx'
    with pytest.raises(ValueError, match='hash differs'):
        export_saved_run(moved, rejected)
    assert not rejected.exists()
    assert clean.read_bytes() == original_clean
