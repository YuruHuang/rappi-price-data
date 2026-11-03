"""Collect, verify, and package updated country workbooks.

The published ``datasets/`` release is intentionally frozen.  This command
creates a new dated release directory instead of changing it in place:

    python -m rappi_co.release_update --out data/updates/20261017 --collect

It collects tobacco and beverage searches at every configured location, then
checks the completed source manifests, hashes, row identities, candidate
membership, and the generated Excel workbooks before publishing the package.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
COUNTRIES = ("ar", "co", "pe", "mx")
COUNTRY_NAMES = {"ar": "Argentina", "co": "Colombia", "pe": "Peru", "mx": "Mexico"}
KEY = ("country_code", "zone_slug", "store_id", "product_id")
SHEETS = ("Technical specifications", "Tobacco products", "SSBs", "Water", "Alcohol")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    csv.field_size_limit(100_000_000)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        if not headers or len(headers) != len(set(headers)):
            raise ValueError(f"invalid CSV headers: {path}")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"malformed CSV row: {path}")
    return headers, rows


def _sheet(path: Path, name: str) -> tuple[list[str], list[dict]]:
    book = load_workbook(path, read_only=True, data_only=False)
    try:
        if name not in book.sheetnames:
            raise ValueError(f"missing worksheet {name}: {path}")
        iterator = book[name].iter_rows(values_only=False)
        headers = [cell.value for cell in next(iterator)]
        if not all(isinstance(value, str) and value for value in headers) or len(headers) != len(set(headers)):
            raise ValueError(f"invalid worksheet headers: {path}/{name}")
        rows = []
        for cells in iterator:
            if any(cell.data_type in {"f", "e"} for cell in cells):
                raise ValueError(f"formula or error in source worksheet: {path}/{name}")
            rows.append({key: cell.value for key, cell in zip(headers, cells)})
        return headers, rows
    finally:
        book.close()


def _identity(row: dict, label: str) -> tuple[str, ...]:
    values = tuple(row.get(column) for column in KEY)
    if not all(isinstance(value, str) and value for value in values):
        raise ValueError(f"missing or non-text identity in {label}: {values}")
    return values


def _record(path: Path, rows: int | None = None) -> dict:
    result = {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}
    if rows is not None:
        result["rows"] = rows
    return result


def _manifest_output(manifest: dict, key: str, root: Path) -> Path:
    record = (manifest.get("outputs") or {}).get(key)
    if not isinstance(record, dict) or not isinstance(record.get("data_root_relative_path"), str):
        raise ValueError(f"completed manifest has no {key} output")
    path = (root / record["data_root_relative_path"]).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"manifest output is absent or outside its data root: {key}")
    if path.stat().st_size != record.get("bytes") or _sha256(path) != record.get("sha256"):
        raise ValueError(f"manifest output hash differs: {path}")
    return path


def _technical_rows(code: str, tobacco_rows: list[dict], audit_rows: list[dict], candidates: list[dict],
                    locations: list[dict] | None = None, cities: list[str] | None = None,
                    collection_dates: list[str] | None = None) -> list[list[str]]:
    dates = sorted({*(collection_dates or []), *(str(row.get("scrape_timestamp", ""))[:8]
                    for row in [*tobacco_rows, *audit_rows] if row.get("scrape_timestamp"))})
    count = (len(locations) if locations is not None else
             len({row["zone_slug"] for row in [*tobacco_rows, *audit_rows] if row.get("zone_slug")}))
    return [
        ["Country", COUNTRY_NAMES[code]],
        ["Purpose", "Updated Rappi product-listing release generated from completed source manifests."],
        ["Collection dates", ", ".join(dates)],
        ["Unit of observation", "One product listing at one store and delivery location at collection time."],
        ["Tobacco rows", str(len(tobacco_rows))],
        ["Beverage audit rows", str(len(audit_rows))],
        ["SSB candidate rows", str(len(candidates))],
        ["Delivery locations", str(count)],
        ["Cities", ", ".join(cities or []) or "Not recorded in the source location records"],
        ["Coverage", f"{count} delivery locations recorded for this country. The release is a finite search, not a national catalog or market-share estimate."],
        ["Interpretation", "Blank values are unavailable or unsupported values, not zero. SSB candidate inclusion does not establish sugar concentration."],
    ]


def _build_country(code: str, tobacco_manifest_path: Path, tobacco_root: Path,
                   beverage_manifest_path: Path, beverage_root: Path, destination: Path) -> dict:
    tobacco_manifest_bytes = tobacco_manifest_path.read_bytes()
    beverage_manifest_bytes = beverage_manifest_path.read_bytes()
    tobacco_manifest = json.loads(tobacco_manifest_bytes)
    beverage_manifest = json.loads(beverage_manifest_bytes)
    if tobacco_manifest.get("country_code") != code or beverage_manifest.get("plan", {}).get("country_code") != code:
        raise ValueError(f"wrong-country source manifest: {code}")
    if beverage_manifest.get("complete") is not True:
        raise ValueError(f"incomplete beverage manifest: {code}")
    tobacco_book = _manifest_output(tobacco_manifest, "xlsx", tobacco_root)
    audit_path = _manifest_output(beverage_manifest, "audit_csv", beverage_root)
    candidates_path = _manifest_output(beverage_manifest, "ssb_candidates_csv", beverage_root)
    _, tobacco_rows = _sheet(tobacco_book, "items")
    _, audit_rows = _csv(audit_path)
    _, candidates = _csv(candidates_path)
    for label, rows in (("tobacco", tobacco_rows), ("beverage audit", audit_rows), ("SSB candidates", candidates)):
        identities = [_identity(row, f"{code}/{label}") for row in rows]
        if len(identities) != len(set(identities)):
            raise ValueError(f"duplicate source identities: {code}/{label}")
    audit_ids = {_identity(row, f"{code}/beverage audit") for row in audit_rows}
    if not {_identity(row, f"{code}/SSB candidates") for row in candidates}.issubset(audit_ids):
        raise ValueError(f"SSB candidates are not an audit subset: {code}")
    audit_by_key = {_identity(row, f"{code}/beverage audit"): row for row in audit_rows}
    for row in candidates:
        original = audit_by_key[_identity(row, f"{code}/SSB candidates")]
        if any(value != original.get(field) for field, value in row.items() if field != 'ssb_candidate_status'):
            raise ValueError(f'SSB candidate content differs from its audit observation: {code}')
    water = [row for row in audit_rows if row.get("beverage_category") == "water"]
    alcohol = [row for row in audit_rows if row.get("beverage_category") == "alcohol"]
    locations_by_slug = {}
    for location in [*(tobacco_manifest.get("location_records") or []),
                     *(beverage_manifest.get("plan", {}).get("addresses") or [])]:
        if not isinstance(location, dict) or not location.get("slug"):
            raise ValueError(f"invalid source location record: {code}")
        slug = location["slug"]
        if slug in locations_by_slug and locations_by_slug[slug] != location:
            raise ValueError(f"source location definitions differ for {code}/{slug}")
        locations_by_slug[slug] = location
    locations = list(locations_by_slug.values()) or None
    cities = sorted({str(location["city"]) for location in (locations or []) if location.get("city")})
    if not cities and not (tobacco_manifest.get("locations_file") or
                           beverage_manifest.get("plan", {}).get("locations_file")):
        cities = sorted({str(city) for city in (tobacco_manifest.get("city"),
                         beverage_manifest.get("plan", {}).get("city")) if city})
    final = destination / f"{COUNTRY_NAMES[code].lower().replace(' ', '_')}.xlsx"
    # Empty successful searches have no product row on which to store a date.
    # Their exact saved source filenames still carry the collection timestamp.
    source_groups = [*(tobacco_manifest.get("inputs", {}).get("sources", {}).values()),
                     *(beverage_manifest.get("inputs", {}).values())]
    collection_dates = set()
    for group in source_groups:
        if isinstance(group, dict):
            item_record = group.get("items", {})
            name = Path(item_record.get("data_root_relative_path", "")).name
            match = re.fullmatch(r"search_items_(\d{8})_\d{6}\.csv", name)
            if match:
                collection_dates.add(match.group(1))
    technical_rows = _technical_rows(code, tobacco_rows, audit_rows, candidates, locations, cities,
                                     sorted(collection_dates))
    from rappi_co.export.integrated_deliverable import canonical_row, observation_key
    from rappi_co.export.product_workbook import (
        technical_specifications, tobacco_tables, write_product_workbook,
    )
    tobacco_release = tobacco_manifest_path.stem.removeprefix('study_manifest_')
    tables = tobacco_tables(tobacco_rows, code, tobacco_release,
                            str(tobacco_book.relative_to(tobacco_root.resolve())))
    tables.update({"SSBs": [], "Water": [], "Alcohol": []})
    candidate_map = {observation_key(row): row for row in candidates}
    beverage_release = beverage_manifest.get('run_id') or beverage_manifest_path.stem
    for index, row in enumerate(audit_rows, 2):
        if row['country_code'] != code:
            raise ValueError(f'wrong-country beverage observation: {code}')
        normalized = canonical_row(row, 'beverages', beverage_release,
                                   str(audit_path.relative_to(beverage_root.resolve())), index, candidate_map)
        name = {'SSB_candidates': 'SSBs', 'Water': 'Water', 'Alcohol': 'Alcohol'}.get(normalized['reporting_group'])
        if name:
            tables[name].append(normalized)
    presentation = write_product_workbook(
        final, COUNTRY_NAMES[code], tables,
        technical=technical_specifications(technical_rows, tables, locations), replace=True,
    )
    for manifest, key, root in ((tobacco_manifest, 'xlsx', tobacco_root),
                                (beverage_manifest, 'audit_csv', beverage_root),
                                (beverage_manifest, 'ssb_candidates_csv', beverage_root)):
        _manifest_output(manifest, key, root)
    if (tobacco_manifest_path.read_bytes() != tobacco_manifest_bytes or
            beverage_manifest_path.read_bytes() != beverage_manifest_bytes):
        raise ValueError('Source manifest changed during country workbook export')
    return {"country_code": code, "file": presentation['workbook'], "sheets": presentation['sheets'], "rows": {
        "tobacco": len(tobacco_rows), "ssb_candidates": len(candidates), "water": len(water), "alcohol": len(alcohol),
    }, "locations": locations or [], "cities": cities,
        "inputs": {"tobacco_manifest": _record(tobacco_manifest_path), "beverage_manifest": _record(beverage_manifest_path),
                     "tobacco_items_workbook": _record(tobacco_book), "beverage_audit": _record(audit_path),
                     "ssb_candidates": _record(candidates_path)}}


def _write_state(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _countries(countries: list[str] | tuple[str, ...] | None) -> list[str]:
    selected = list(COUNTRIES) if countries is None else list(countries)
    if not selected or len(selected) != len(set(selected)) or set(selected) - set(COUNTRIES):
        raise ValueError("select at least one country without duplicates; expected ar, co, pe, mx")
    # A country set has one canonical ordering, including when resuming.
    return [code for code in COUNTRIES if code in selected]


def _terms(terms: list[str] | tuple[str, ...] | None) -> list[str] | None:
    if terms is None:
        return None
    if not terms or any(not isinstance(term, str) or not term.strip() for term in terms):
        raise ValueError("query overrides must contain nonempty text")
    return list(dict.fromkeys(term.strip() for term in terms))


def _plan_selection(countries=None, locations_file=None, tobacco_terms=None,
                    beverage_terms=None, input_files=None) -> dict:
    """Validate the whole selection before any output creation or network call."""
    from rappi_co import beverages, study
    from rappi_co.locations import location_file_record, validate_location_scope

    selected = _countries(countries)
    tobacco_terms, beverage_terms = _terms(tobacco_terms), _terms(beverage_terms)
    if locations_file is not None:
        validate_location_scope(locations_file, selected)
    plans = {
        "tobacco": [study.plan_country(code, terms=tobacco_terms, locations_file=locations_file)
                    for code in selected],
        "beverages": [beverages.plan_country(code, terms=beverage_terms, locations_file=locations_file)
                      for code in selected],
    }
    configurations = {str(path.relative_to(ROOT)): _sha256(path)
                      for path in sorted((ROOT / "config").rglob("*"))
                      if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}}
    return {
        "countries": selected,
        "plans": plans,
        "locations_file": location_file_record(locations_file) if locations_file is not None else None,
        "location_counts": {plan["country_code"]: len(plan["addresses"]) for plan in plans["tobacco"]},
        "configuration_sha256": configurations,
        "input_files": [_record(Path(path)) for path in (input_files or [])],
    }


def collect_and_build(out: Path, min_delay: float, max_delay: float, *, resume: bool = False,
                      countries=None, locations_file=None, tobacco_terms=None,
                      beverage_terms=None, input_files=None) -> dict:
    out = Path(out)
    if (not math.isfinite(min_delay) or not math.isfinite(max_delay)
            or min_delay < 0 or max_delay < min_delay):
        raise ValueError("delays must satisfy finite 0 <= min_delay <= max_delay")
    selection = _plan_selection(countries, locations_file, tobacco_terms, beverage_terms, input_files)
    state_path = out / "update_state.json"
    if out.exists() and not resume:
        raise FileExistsError(f"destination must be new (or use --resume): {out}")
    if resume and not state_path.is_file():
        raise FileNotFoundError(f"no resumable update state: {state_path}")
    state = (json.loads(state_path.read_text(encoding="utf-8")) if resume else
             {"schema_version": 2, "status": "in_progress", "completed": {}, "selection": selection})
    if resume and state.get("selection") != selection:
        raise ValueError("resume plan differs from the saved countries, locations, queries, or configuration; use the original inputs or a new output directory")
    if (not isinstance(state.get("completed"), dict)
            or set(state["completed"]) - set(selection["countries"])):
        raise ValueError("resume state contains invalid completed countries")
    from rappi_co import beverages, study
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=resume)
    if locations_file is not None:
        snapshot = out / "inputs" / f"locations{Path(locations_file).suffix.lower()}"
        expected_hash = selection["locations_file"]["sha256"]
        if resume:
            if (not snapshot.is_file() or _sha256(snapshot) != expected_hash
                    or state.get("input_snapshot", {}).get("sha256") != expected_hash):
                raise ValueError("saved delivery-location input snapshot is missing or differs")
        else:
            content = Path(locations_file).read_bytes()
            if hashlib.sha256(content).hexdigest() != expected_hash:
                raise ValueError("delivery-location input changed during planning")
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(content)
            state["input_snapshot"] = _record(snapshot)
    extra_snapshots = []
    for index, record in enumerate(selection["input_files"], 1):
        source = Path(record["path"])
        snapshot = out / "inputs" / f"terms_{index:02d}_{source.name}"
        if resume:
            if not snapshot.is_file() or _sha256(snapshot) != record["sha256"]:
                raise ValueError("saved query-input snapshot is missing or differs")
        else:
            content = source.read_bytes()
            if hashlib.sha256(content).hexdigest() != record["sha256"]:
                raise ValueError("query-input file changed during planning")
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(content)
        extra_snapshots.append(_record(snapshot))
    state["extra_input_snapshots"] = extra_snapshots
    _write_state(state_path, state)
    tobacco_root, beverage_root = out / "raw" / "tobacco", out / "raw" / "beverages"
    try:
        for code in selection["countries"]:
            if _plan_selection(selection["countries"], locations_file, tobacco_terms, beverage_terms, input_files) != selection:
                raise ValueError("locations, query plans, or configuration changed during collection")
            if code in state["completed"]:
                continue
            tobacco = study.run_country(code, data_root=tobacco_root, min_delay=min_delay, max_delay=max_delay,
                                        terms=_terms(tobacco_terms), locations_file=locations_file)
            beverage = beverages.run_country(code, data_root=beverage_root, min_delay=min_delay, max_delay=max_delay,
                                             terms=_terms(beverage_terms), locations_file=locations_file)
            state["completed"][code] = {
                "tobacco_manifest": tobacco["deliverable"]["manifest"],
                "beverage_manifest": beverage["deliverable"]["manifest"],
            }
            _write_state(state_path, state)
        if _plan_selection(selection["countries"], locations_file, tobacco_terms, beverage_terms, input_files) != selection:
            raise ValueError("locations, query plans, or configuration changed during collection")
        sheets = out / "country_products"
        sheets.mkdir(exist_ok=True)
        countries = []
        for code in selection["countries"]:
            completed = state["completed"][code]
            countries.append(_build_country(code, Path(completed["tobacco_manifest"]), tobacco_root,
                                            Path(completed["beverage_manifest"]), beverage_root, sheets))
        manifest = {"schema_version": 2, "status": "verified_updated_country_workbooks",
                    "created_at_utc": datetime.now(timezone.utc).isoformat(), "countries": countries,
                    "selection": selection,
                    "input_snapshot": state.get("input_snapshot"),
                    "extra_input_snapshots": extra_snapshots,
                    "collection_requested": True, "network_requests": "recorded in each completed source manifest",
                    "checks": ["completed source-manifest hashes", "source row identities", "candidate subset of beverage audit",
                               "category partitions", "workbook ZIP integrity", "workbook headers, row counts, and formula/error cells"],
                    "limitations": ["finite search at the delivery locations recorded in this release", "collection dates can differ across tobacco and beverages",
                                    "SSB candidates do not establish sugar concentration"]}
        manifest_path = out / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        state_path.unlink()
        return manifest
    except BaseException as error:
        state["status"] = "failed"
        state["error"] = str(error)
        _write_state(state_path, state)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new dated release directory")
    parser.add_argument("--country", action="append", choices=COUNTRIES,
                        help="country code; repeat to select several; omit for all four")
    parser.add_argument("--locations-file", type=Path, help="CSV, TSV, JSON, YAML or XLSX delivery points")
    parser.add_argument("--tobacco-terms", help="comma-separated tobacco query override")
    parser.add_argument("--beverage-terms", help="comma-separated beverage query override")
    parser.add_argument("--collect", action="store_true", help="collect and build the selected countries")
    parser.add_argument("--dry-run", action="store_true", help="print the configured country plans without network requests")
    parser.add_argument("--resume", action="store_true", help="resume an interrupted collection in --out")
    parser.add_argument("--min-delay", type=float, default=1.0)
    parser.add_argument("--max-delay", type=float, default=3.0)
    args = parser.parse_args(argv)
    if args.collect == args.dry_run or (args.resume and not args.collect):
        parser.error("choose exactly one of --collect or --dry-run")
    try:
        countries = _countries(args.country)
        tobacco_terms = _terms(args.tobacco_terms.split(",")) if args.tobacco_terms is not None else None
        beverage_terms = _terms(args.beverage_terms.split(",")) if args.beverage_terms is not None else None
    except ValueError as error:
        parser.error(str(error))
    if args.dry_run:
        selection = _plan_selection(countries, args.locations_file, tobacco_terms, beverage_terms)
        print(json.dumps(selection["plans"], ensure_ascii=False, indent=2))
        return 0
    result = collect_and_build(args.out, args.min_delay, args.max_delay, resume=args.resume,
                               countries=countries, locations_file=args.locations_file,
                               tobacco_terms=tobacco_terms, beverage_terms=beverage_terms)
    print(json.dumps({"status": result["status"], "countries": [entry["country_code"] for entry in result["countries"]]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
