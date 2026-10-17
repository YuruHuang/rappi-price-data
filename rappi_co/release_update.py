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
import shutil
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.utils import get_column_letter


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


def _write_sheet(book: Workbook, title: str, headers: list[str], rows: list[dict]) -> None:
    sheet = book.create_sheet(title)
    sheet.freeze_panes = "A2"
    sheet.append(headers)
    for row in rows:
        values = []
        for header in headers:
            value = row.get(header)
            cell = WriteOnlyCell(sheet, value)
            if isinstance(value, str):
                cell.data_type = "s"
                cell.number_format = "@"
            values.append(cell)
        sheet.append(values)
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"


def _technical_rows(code: str, tobacco_rows: list[dict], audit_rows: list[dict], candidates: list[dict]) -> list[list[str]]:
    dates = sorted({str(row.get("scrape_timestamp", ""))[:8] for row in [*tobacco_rows, *audit_rows] if row.get("scrape_timestamp")})
    return [
        ["Country", COUNTRY_NAMES[code]],
        ["Purpose", "Updated Rappi product-listing release generated from completed source manifests."],
        ["Collection dates", ", ".join(dates)],
        ["Unit of observation", "One product listing at one store and delivery location at collection time."],
        ["Tobacco rows", str(len(tobacco_rows))],
        ["Beverage audit rows", str(len(audit_rows))],
        ["SSB candidate rows", str(len(candidates))],
        ["Coverage", "Two configured delivery locations per country. The release is a finite search, not a national catalog or market-share estimate."],
        ["Interpretation", "Blank values are unavailable or unsupported values, not zero. SSB candidate inclusion does not establish sugar concentration."],
    ]


def _validate_workbook(path: Path, expected: dict[str, tuple[list[str], list[dict]]]) -> None:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"corrupt workbook: {path}")
    book = load_workbook(path, read_only=True, data_only=False)
    try:
        if book.sheetnames != list(SHEETS):
            raise ValueError(f"unexpected sheet order: {path}")
        for name, (headers, rows) in expected.items():
            iterator = book[name].iter_rows(values_only=False)
            found_headers = [cell.value for cell in next(iterator)]
            if found_headers != headers:
                raise ValueError(f"header mismatch: {path}/{name}")
            found = list(iterator)
            if len(found) != len(rows):
                raise ValueError(f"row-count mismatch: {path}/{name}")
            for cells, source in zip(found, rows, strict=True):
                if any(cell.data_type in {"f", "e"} for cell in cells):
                    raise ValueError(f"formula or error in output: {path}/{name}")
    finally:
        book.close()


def _build_country(code: str, tobacco_manifest_path: Path, tobacco_root: Path,
                   beverage_manifest_path: Path, beverage_root: Path, destination: Path) -> dict:
    tobacco_manifest = json.loads(tobacco_manifest_path.read_text(encoding="utf-8"))
    beverage_manifest = json.loads(beverage_manifest_path.read_text(encoding="utf-8"))
    if tobacco_manifest.get("country_code") != code or beverage_manifest.get("plan", {}).get("country_code") != code:
        raise ValueError(f"wrong-country source manifest: {code}")
    if beverage_manifest.get("complete") is not True:
        raise ValueError(f"incomplete beverage manifest: {code}")
    tobacco_book = _manifest_output(tobacco_manifest, "xlsx", tobacco_root)
    audit_path = _manifest_output(beverage_manifest, "audit_csv", beverage_root)
    candidates_path = _manifest_output(beverage_manifest, "ssb_candidates_csv", beverage_root)
    tobacco_headers, tobacco_rows = _sheet(tobacco_book, "items")
    audit_headers, audit_rows = _csv(audit_path)
    candidate_headers, candidates = _csv(candidates_path)
    for label, rows in (("tobacco", tobacco_rows), ("beverage audit", audit_rows), ("SSB candidates", candidates)):
        identities = [_identity(row, f"{code}/{label}") for row in rows]
        if len(identities) != len(set(identities)):
            raise ValueError(f"duplicate source identities: {code}/{label}")
    audit_ids = {_identity(row, f"{code}/beverage audit") for row in audit_rows}
    if not {_identity(row, f"{code}/SSB candidates") for row in candidates}.issubset(audit_ids):
        raise ValueError(f"SSB candidates are not an audit subset: {code}")
    water = [row for row in audit_rows if row.get("beverage_category") == "water"]
    alcohol = [row for row in audit_rows if row.get("beverage_category") == "alcohol"]
    final = destination / f"{COUNTRY_NAMES[code].lower().replace(' ', '_')}.xlsx"
    book = Workbook(write_only=True)
    book.properties.creator = "Rappi product study"
    book.properties.title = f"Rappi product listings — {COUNTRY_NAMES[code]}"
    technical_rows = _technical_rows(code, tobacco_rows, audit_rows, candidates)
    technical = book.create_sheet(SHEETS[0])
    technical.freeze_panes = "A2"
    technical.append(["Item", "Description"])
    for row in technical_rows:
        technical.append(row)
    technical.auto_filter.ref = f"A1:B{len(technical_rows) + 1}"
    _write_sheet(book, "Tobacco products", tobacco_headers, tobacco_rows)
    _write_sheet(book, "SSBs", candidate_headers, candidates)
    _write_sheet(book, "Water", audit_headers, water)
    _write_sheet(book, "Alcohol", audit_headers, alcohol)
    book.save(final)
    _validate_workbook(final, {
        "Tobacco products": (tobacco_headers, tobacco_rows), "SSBs": (candidate_headers, candidates),
        "Water": (audit_headers, water), "Alcohol": (audit_headers, alcohol),
    })
    return {"country_code": code, "file": _record(final), "rows": {
        "tobacco": len(tobacco_rows), "ssb_candidates": len(candidates), "water": len(water), "alcohol": len(alcohol),
    }, "inputs": {"tobacco_manifest": _record(tobacco_manifest_path), "beverage_manifest": _record(beverage_manifest_path),
                     "tobacco_items_workbook": _record(tobacco_book), "beverage_audit": _record(audit_path),
                     "ssb_candidates": _record(candidates_path)}}


def collect_and_build(out: Path, min_delay: float, max_delay: float) -> dict:
    if out.exists():
        raise FileExistsError(f"destination must be new: {out}")
    from rappi_co import beverages, study
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".country-update-", dir=out.parent))
    tobacco_root, beverage_root = staging / "raw" / "tobacco", staging / "raw" / "beverages"
    try:
        tobacco_runs, beverage_runs = {}, {}
        for code in COUNTRIES:
            tobacco_runs[code] = study.run_country(code, data_root=tobacco_root, min_delay=min_delay, max_delay=max_delay)
            beverage_runs[code] = beverages.run_country(code, data_root=beverage_root, min_delay=min_delay, max_delay=max_delay)
        sheets = staging / "country_products"
        sheets.mkdir()
        countries = []
        for code in COUNTRIES:
            countries.append(_build_country(code, Path(tobacco_runs[code]["deliverable"]["manifest"]), tobacco_root,
                                            Path(beverage_runs[code]["deliverable"]["manifest"]), beverage_root, sheets))
        manifest = {"schema_version": 1, "status": "verified_updated_country_workbooks",
                    "created_at_utc": datetime.now(timezone.utc).isoformat(), "countries": countries,
                    "collection_requested": True, "network_requests": "recorded in each completed source manifest",
                    "checks": ["completed source-manifest hashes", "source row identities", "candidate subset of beverage audit",
                               "category partitions", "workbook ZIP integrity", "workbook headers, row counts, and formula/error cells"],
                    "limitations": ["finite two-location search per country", "collection dates can differ across tobacco and beverages",
                                    "SSB candidates do not establish sugar concentration"]}
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if out.exists():
            raise FileExistsError(f"destination appeared during build: {out}")
        staging.rename(out)
        return manifest
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new dated release directory")
    parser.add_argument("--collect", action="store_true", help="collect and build all four countries")
    parser.add_argument("--dry-run", action="store_true", help="print the configured country plans without network requests")
    parser.add_argument("--min-delay", type=float, default=1.0)
    parser.add_argument("--max-delay", type=float, default=3.0)
    args = parser.parse_args(argv)
    if args.collect == args.dry_run:
        parser.error("choose exactly one of --collect or --dry-run")
    if args.dry_run:
        from rappi_co import beverages, study
        print(json.dumps({"tobacco": [study.plan_country(code) for code in COUNTRIES],
                          "beverages": [beverages.plan_country(code) for code in COUNTRIES]}, ensure_ascii=False, indent=2))
        return 0
    result = collect_and_build(args.out, args.min_delay, args.max_delay)
    print(json.dumps({"status": result["status"], "countries": [entry["country_code"] for entry in result["countries"]]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
