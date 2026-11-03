"""Shared presentation for fresh country collections and completed saved runs.

Use ``python -m rappi_co.export.product_workbook --run-dir RUN_FOLDER`` to
format a completed run without collecting or changing any classifications.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import tempfile

from openpyxl import load_workbook

from rappi_co.export.country_product_workbooks import (
    CountryExcel, DEFINITION_OVERRIDES, DISPLAY, FIELD_SETS, HIDDEN_FIELDS,
    SHEET_HIDDEN_FIELDS, SHEETS, TECHNICAL_FIELDS, TECHNICAL_LABELS, UNITS,
)
from rappi_co.export.integrated_deliverable import canonical_row, observation_key


def _validate(path: Path, expected: dict[str, list[dict]]) -> None:
    book = load_workbook(path, read_only=True, data_only=False)
    try:
        if book.sheetnames != list(expected):
            raise ValueError("Unexpected country product worksheets")
        for name, rows in expected.items():
            fields = TECHNICAL_FIELDS if name == 'Technical specifications' else FIELD_SETS[name]
            labels = TECHNICAL_LABELS if name == 'Technical specifications' else tuple(DISPLAY[field] for field in fields)
            iterator = book[name].iter_rows(min_col=1, max_col=len(fields))
            if tuple(cell.value for cell in next(iterator)) != labels:
                raise ValueError(f"Product headers differ: {name}")
            count = 0
            for count, cells in enumerate(iterator, 1):
                if count > len(rows):
                    raise ValueError(f"Extra product rows: {name}")
                for field, cell in zip(fields, cells, strict=True):
                    value = rows[count - 1].get(field)
                    if value == '':
                        value = None
                    if field == 'discount_pct' and value is not None:
                        value = float(value)
                    if cell.data_type in {'f', 'e'}:
                        raise ValueError(f"Formula or error in product output: {name}/{field}")
                    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
                    if numeric:
                        equal = (isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool)
                                 and math.isclose(cell.value, value, rel_tol=1e-12, abs_tol=1e-10))
                    else:
                        equal = cell.value == value
                    if not equal:
                        raise ValueError(f"Product value differs from source: {name}/{field}")
            if count != len(rows):
                raise ValueError(f"Product row count differs: {name}")
    finally:
        book.close()


def technical_specifications(overview: list[list[str]], tables: dict[str, list[dict]],
                             locations: list[dict] | None = None) -> list[dict]:
    """Use the published technical sheet layout with metadata from this run."""
    from rappi_co.beverages import definition
    from rappi_co.export.study_deliverable import ITEM_DEFINITIONS
    result = [{"section": "Overview", "item": key, "description": str(value)} for key, value in overview]
    for name, rows in tables.items():
        description = ("Screening cohort; candidate membership does not confirm sweetening."
                       if name == 'SSBs' else 'Saved product listings from this collection.')
        result.append({"section": "Category summary", "item": name, "description": description,
                       "applies_to": name, "coverage": f'{len(rows):,} observations'})
    for location in locations or []:
        coordinates = f"Latitude {location.get('lat', '')}; longitude {location.get('lng', '')}."
        result.append({"section": "Locations", "item": location['slug'],
                       "description": str(location.get('address') or ''),
                       "coverage": coordinates, "applies_to": str(location.get('city') or '')})
    result.append({"section": "Reading notes", "item": "Missing values",
                   "description": "Blank measurements are unknown or unsupported, not zero. Listing availability is not verified inventory or a completed purchase."})
    if 'SSBs' in tables:
        result.append({"section": "Reading notes", "item": "SSB candidates",
                       "description": "The SSB tab preserves the saved screening cohort, including records whose added-sugar status is unconfirmed. See SSB candidate status and Sugar information status."})
    uses = {}
    for name in tables:
        for field in FIELD_SETS[name]:
            uses.setdefault(field, []).append(name)
    for field, names in uses.items():
        original = field.removeprefix('tobacco_') if field.startswith('tobacco_') else field
        explanation = DEFINITION_OVERRIDES.get(field) or ITEM_DEFINITIONS.get(original) or definition(original)
        explanation = {
            'source_file': 'Path of the saved source table within its collection data root.',
            'source_row': 'One-based record number in the saved source table; the header is row 1.',
            'source_term': 'First query associated with this observation.',
            'source_terms': 'All saved search queries associated with this observation.',
            'source_release': 'Identifier of the completed source run used for this workbook.',
            'source_collection_date': 'Date parsed from the saved collection timestamp.',
            'record_id': 'Source topic, source run and exact country, delivery-point, store and product identity.',
        }.get(field, explanation)
        hidden = [field in HIDDEN_FIELDS or field in SHEET_HIDDEN_FIELDS.get(name, set()) for name in names]
        section = 'Shared fields' if len(names) > 1 else {
            'Tobacco products': 'Tobacco fields', 'SSBs': 'SSB fields',
            'Water': 'Water fields', 'Alcohol': 'Alcohol fields'}[names[0]]
        result.append({'section': section, 'item': DISPLAY[field], 'description': explanation,
                       'applies_to': ', '.join(names), 'format_unit': UNITS.get(field, ''),
                       'default_view': 'Hidden' if all(hidden) else 'Varies by tab' if any(hidden) else 'Visible',
                       'source_field': field})
    return result


def write_product_workbook(out: Path, country: str | None, tables: dict[str, list[dict]],
                           *, technical: list[dict] | None = None, replace: bool = False) -> dict:
    """Use the unchanged published formatter for every collection scope."""
    from rappi_co.release_update import _record
    out = Path(out)
    if out.exists() and not replace:
        raise FileExistsError(f'Choose a new workbook filename: {out}')
    expected = ({'Technical specifications': technical} if technical is not None else {})
    expected.update({name: tables[name] for name in SHEETS if name in tables})
    if not tables or set(tables) - set(FIELD_SETS):
        raise ValueError('Choose country product tables')
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.country-products-', dir=out.parent) as directory:
        temporary = Path(directory) / out.name
        excel = CountryExcel(temporary, country)
        for name in tuple(excel.sheets):
            if name not in expected:
                excel.workbook.remove(excel.sheets.pop(name))
        for name, rows in expected.items():
            fields = TECHNICAL_FIELDS if name == 'Technical specifications' else FIELD_SETS[name]
            labels = TECHNICAL_LABELS if name == 'Technical specifications' else None
            excel.table(name, fields, labels)
            for row in rows:
                excel.append(name, row)
        excel.save()
        _validate(temporary, expected)
        if out.exists() and not replace:
            raise FileExistsError(f'Choose a new workbook filename: {out}')
        temporary.replace(out)
    return {'workbook': _record(out.resolve()), 'sheets': list(expected),
            'rows': {name: len(rows) for name, rows in tables.items()}}


def tobacco_tables(rows: list[dict], code: str, release: str, source: str) -> dict[str, list[dict]]:
    normalized, seen = [], set()
    for index, row in enumerate(rows, 2):
        key = observation_key(row)
        if row['country_code'] != code or key in seen:
            raise ValueError('Wrong country or duplicate tobacco observation')
        seen.add(key)
        normalized.append(canonical_row(row, 'tobacco', release, source, index, {}))
    return {'Tobacco products': normalized}


def export_tobacco_workbook(manifest_path: Path, data_root: Path, out: Path) -> dict:
    from rappi_co.release_update import COUNTRY_NAMES, _csv, _manifest_output, _record, _technical_rows
    manifest_path, data_root, out = Path(manifest_path).resolve(), Path(data_root).resolve(), Path(out)
    sidecar = out.with_suffix('.manifest.json')
    if out.exists() or sidecar.exists():
        raise FileExistsError(f'Choose a new workbook filename: {out}')
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    code = manifest.get('country_code')
    if code not in COUNTRY_NAMES or manifest.get('schema_version') != 2:
        raise ValueError('Expected a completed tobacco source manifest')
    source = _manifest_output(manifest, 'items_csv', data_root)
    _, rows = _csv(source)
    if manifest.get('counts', {}).get('tobacco_observations') != len(rows):
        raise ValueError('Saved tobacco count differs from the source manifest')
    release = manifest_path.stem.removeprefix('study_manifest_')
    tables = tobacco_tables(rows, code, release, str(source.relative_to(data_root)))
    locations = manifest.get('location_records') or []
    dates = set()
    for record in manifest.get('inputs', {}).get('sources', {}).values():
        filename = Path(record.get('items', {}).get('data_root_relative_path', '')).name
        match = re.fullmatch(r'search_items_(\d{8})_\d{6}\.csv', filename)
        if match:
            dates.add(match.group(1))
    overview = _technical_rows(code, rows, [], [], locations,
                               sorted({str(row.get('city')) for row in locations if row.get('city')}),
                               collection_dates=sorted(dates))
    overview = [row for row in overview if row[0] not in {'Beverage audit rows', 'SSB candidate rows'}]
    technical = technical_specifications(overview, tables, locations)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.tobacco-products-', dir=out.parent) as directory:
        temporary = Path(directory) / out.name
        result = write_product_workbook(temporary, COUNTRY_NAMES[code], tables, technical=technical)
        if manifest_path.read_bytes() != manifest_bytes:
            raise ValueError('Tobacco source manifest changed during export')
        _manifest_output(manifest, 'items_csv', data_root)
        if out.exists() or sidecar.exists():
            raise FileExistsError(f'Choose a new workbook filename: {out}')
        temporary.replace(out)
        result.update(status='verified_tobacco_product_workbook', country_code=code,
                      source_manifest=_record(manifest_path), sources={'items_csv': _record(source)},
                      workbook=_record(out.resolve()))
        sidecar.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def _find_manifest(root: Path, source: str) -> Path:
    matches = list(root.glob(f'*/processed/**/{Path(source).name}'))
    if len(matches) != 1:
        raise ValueError('Cannot locate exactly one saved source manifest')
    return matches[0]


def export_saved_run(run_dir: Path, out: Path | None = None, country: str | None = None) -> list[dict]:
    from rappi_co.export.beverage_workbook import export_saved_run as export_beverages
    from rappi_co.release_update import _build_country, _record
    run_dir = Path(run_dir).resolve()
    wrapper = json.loads((run_dir / 'manifest.json').read_text(encoding='utf-8'))
    if wrapper.get('status') == 'completed_country_collection':
        code, scope = wrapper.get('country_code'), wrapper.get('scope')
        if country is not None and country != code:
            raise ValueError('The requested country differs from the saved run')
        if scope == 'beverages':
            return [export_beverages(run_dir, out)]
        if scope != 'tobacco':
            raise ValueError('Choose a completed tobacco, beverage or combined run')
        source = wrapper.get('result', {}).get('deliverable', {}).get('manifest')
        if not source:
            raise ValueError('The run does not identify its source manifest')
        target = Path(out) if out is not None else run_dir / 'country_products' / f'{code}_tobacco_clean.xlsx'
        root = run_dir / 'source'
        manifest = _find_manifest(root, source)
        if json.loads(manifest.read_text())['country_code'] != code:
            raise ValueError('Saved run and source countries differ')
        return [export_tobacco_workbook(manifest, root, target)]
    if wrapper.get('status') != 'verified_updated_country_workbooks':
        raise ValueError('Choose a completed country-team run folder')
    entries = [entry for entry in wrapper['countries'] if country is None or entry['country_code'] == country]
    if not entries:
        raise ValueError('The requested country is absent from this saved run')
    if out is not None and len(entries) != 1:
        raise ValueError('Select one --country when choosing an --out filename for a multi-country run')
    results = []
    for entry in entries:
        code = entry['country_code']
        target = Path(out) if out is not None else run_dir / 'country_products' / f'{code}_products_clean.xlsx'
        sidecar = target.with_suffix('.manifest.json')
        if target.exists() or sidecar.exists():
            raise FileExistsError(f'Choose a new workbook filename: {target}')
        tobacco_root, beverage_root = run_dir / 'raw/tobacco', run_dir / 'raw/beverages'
        tobacco_manifest = _find_manifest(tobacco_root, entry['inputs']['tobacco_manifest']['path'])
        beverage_manifest = _find_manifest(beverage_root, entry['inputs']['beverage_manifest']['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.country-products-', dir=target.parent) as directory:
            result = _build_country(code, tobacco_manifest, tobacco_root,
                                    beverage_manifest, beverage_root, Path(directory))
            generated = Path(result['file']['path'])
            generated.replace(target)
            result['file'] = _record(target.resolve())
            sidecar.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        results.append(result)
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True, type=Path, help='completed country-team run folder')
    parser.add_argument('--out', type=Path, help='new workbook filename; the existing workbook is retained')
    parser.add_argument('--country', choices=['ar', 'co', 'pe', 'mx'], help='optional country within a combined run')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(export_saved_run(args.run_dir, args.out, args.country), ensure_ascii=False, indent=2))
    except (OSError, ValueError) as error:
        parser.exit(2, f'error: {error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
