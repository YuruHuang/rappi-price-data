"""Run the search-first multicountry study without changing the Colombia release."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from rappi_co.classify.run import run_classify
from rappi_co.collect.search import run as run_search
from rappi_co.configs import load_study_profile, study_queries
from rappi_co.export.study_deliverable import run_export


ROOT = Path(__file__).resolve().parents[1]
STUDY_CONFIG = ROOT / "config" / "study"
COUNTRIES = ("ar", "co", "pe", "mx")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _csv_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.reader(handle)
        next(rows, None)
        return sum(1 for _ in rows)


def _file_record(path: str | Path, data_root: Path, *, rows: bool = False) -> dict:
    resolved = Path(path).resolve()
    root = data_root.resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"processed study artifact must be inside data_root: {resolved}"
        ) from exc
    record = {
        "data_root_relative_path": relative,
        "bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }
    if rows:
        record["rows"] = _csv_row_count(resolved)
    return record


def _source_timestamp(source: str | Path) -> str:
    match = re.fullmatch(r"search_items_(\d{8}_\d{6})\.csv", Path(source).name)
    if not match:
        raise ValueError(f"unexpected study source filename: {Path(source).name}")
    return match.group(1)


def _run_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    work = path.with_name(f".{path.name}.partial")
    try:
        with work.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        work.replace(path)
    finally:
        if work.exists():
            work.unlink()


def _write_processed_manifest(country: str, plan: dict, sources: dict[str, str],
                              classifications: dict[str, str], deliverable: dict,
                              data_root: Path) -> Path:
    source_records = {}
    for slug, source_value in sources.items():
        source = Path(source_value)
        timestamp = _source_timestamp(source)
        collection_manifest = source.with_name(f"search_manifest_{timestamp}.json")
        if not collection_manifest.is_file():
            raise FileNotFoundError(
                f"collection manifest not found for processed source {source}"
            )
        source_records[slug] = {
            "items": _file_record(source, data_root, rows=True),
            "collection_manifest": _file_record(collection_manifest, data_root),
        }

    classification_records = {
        slug: _file_record(path, data_root, rows=True)
        for slug, path in classifications.items()
    }
    output_records = {
        key: _file_record(path, data_root, rows=key.endswith("_csv"))
        for key, path in deliverable.items()
        if key in {"items_csv", "stores_csv", "locations_csv", "xlsx"}
    }
    items_path = Path(deliverable["items_csv"])
    match = re.fullmatch(
        r"tobacco_items_(\d{8}_\d{6}_\d{6})\.csv", items_path.name)
    if not match:
        raise ValueError(f"unexpected study deliverable filename: {items_path.name}")
    manifest_path = items_path.with_name(f"study_manifest_{match.group(1)}.json")
    payload = {
        "schema_version": 2,
        "path_base": "data_root",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "protocol_status": plan["protocol_status"],
        "full_protocol": plan["full_protocol"],
        "country_code": country,
        "country": plan["country"],
        "city": plan["city"],
        "currency": plan["currency"],
        "locations": [zone["slug"] for zone in plan["addresses"]],
        "queries": list(plan["queries"]),
        "query_count": len(plan["queries"]),
        "request_count": plan["requests"],
        "inputs": {
            "sources": source_records,
            "classifications": classification_records,
        },
        "outputs": output_records,
        "counts": {
            "source_rows": sum(record["items"]["rows"]
                               for record in source_records.values()),
            "classification_rows": sum(record["rows"]
                                       for record in classification_records.values()),
            "tobacco_observations": int(deliverable["n_observations"]),
            "store_location_observations": int(deliverable["n_store_observations"]),
            "locations": len(plan["addresses"]),
        },
    }
    _write_json_atomic(manifest_path, payload)
    return manifest_path


def _manifest_member(directory: Path, value, expected_name: str) -> Path | None:
    """Resolve one manifest member only when it is the expected direct child."""
    if not isinstance(value, str) or not value or Path(value).name != value:
        return None
    if value != expected_name:
        return None
    base = directory.resolve()
    direct = directory / value
    if direct.is_symlink():
        return None
    candidate = direct.resolve()
    if candidate != base / expected_name:
        return None
    return candidate


def _csv_matches_manifest(path: Path, expected_rows, required_columns: set[str]) -> bool:
    """Fail closed when a saved collection CSV is truncated or has the wrong schema."""
    if (isinstance(expected_rows, bool) or not isinstance(expected_rows, int)
            or expected_rows < 0):
        return False
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not required_columns.issubset(reader.fieldnames):
                return False
            return sum(1 for _ in reader) == expected_rows
    except (OSError, UnicodeError, csv.Error):
        return False


def _complete_raw_archive(raw_directory: Path, manifest: dict,
                          queries: list[str]) -> bool:
    """Validate every response archive while accepting both saved filename layouts."""
    term_results = manifest.get("term_results")
    if (manifest.get("request_count") != len(queries)
            or not isinstance(term_results, list)
            or len(term_results) != len(queries)
            or [result.get("query") for result in term_results
                if isinstance(result, dict)] != queries):
        return False
    raw_files = sorted(raw_directory.glob("*.json.gz"))
    if len(raw_files) != len(queries):
        return False

    # New collectors record the collision-proof indexed filename for every query.
    # Older archived study runs omit raw_file; the exact count and payload checks
    # retain backward compatibility with that schema-1 layout.
    named = [result.get("raw_file") for result in term_results]
    if any(value is not None for value in named):
        if (any(not isinstance(value, str) or Path(value).name != value for value in named)
                or {path.name for path in raw_files} != set(named)):
            return False
    try:
        for path in raw_files:
            # A response archive must be a real file inside this run's archive.
            # Following a symlink here would let a manifest claim a payload that
            # actually lives in another run (or outside data_root altogether).
            if path.is_symlink() or path.resolve().parent != raw_directory.resolve():
                return False
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict) or not isinstance(payload.get("stores"), list):
                return False
    except (OSError, UnicodeError, ValueError):
        return False
    return True


def _complete_source(directory: Path, country: str, address: str,
                     queries: list[str]) -> Path:
    manifests = sorted(directory.glob("search_manifest_*.json"), reverse=True)
    for path in manifests:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(manifest, dict):
            continue
        if (manifest.get("complete") is not True
                or manifest.get("country_code") != country
                or manifest.get("address") != address
                or manifest.get("queries") != queries):
            continue
        match = re.fullmatch(r"search_manifest_(\d{8}_\d{6})\.json", path.name)
        if not match:
            continue
        timestamp = match.group(1)
        source = _manifest_member(
            directory, manifest.get("items"), f"search_items_{timestamp}.csv")
        stores = _manifest_member(
            directory, manifest.get("stores"), f"search_stores_{timestamp}.csv")
        raw_directory = _manifest_member(
            directory, manifest.get("raw_directory"), f"search_raw_{timestamp}")
        if (source is not None and stores is not None and raw_directory is not None
                and source.is_file() and stores.is_file() and raw_directory.is_dir()
                and _csv_matches_manifest(
                    source, manifest.get("n_items"), {"store_id", "product_id"})
                and _csv_matches_manifest(
                    stores, manifest.get("n_stores"), {"store_id"})
                and _complete_raw_archive(raw_directory, manifest, queries)):
            return source
    raise FileNotFoundError(
        f"no complete {country}/{address} collection matches the expected {len(queries)} queries; "
        "run collection first or pass the same --terms used for the saved run"
    )


def plan_country(country: str, addresses: list[str] | None = None,
                 terms: list[str] | None = None) -> dict:
    profile = load_study_profile(country, STUDY_CONFIG)
    configured = {zone["slug"]: zone for zone in profile["zones"]}
    slugs = addresses or list(configured)
    if len(slugs) != len(set(slugs)):
        raise ValueError(f"duplicate {country} addresses are not allowed")
    unknown = set(slugs) - set(configured)
    if unknown:
        raise ValueError(f"unknown {country} addresses: {sorted(unknown)}")
    queries = terms or study_queries(profile)
    full_protocol = (len(slugs) == len(configured)
                     and set(slugs) == set(configured)
                     and queries == study_queries(profile))
    return {
        "country_code": country,
        "country": profile["name"],
        "city": profile["city"],
        "currency": profile["currency"],
        "addresses": [configured[slug] for slug in slugs],
        "queries": queries,
        "requests": len(slugs) * len(queries),
        "protocol_status": "full" if full_protocol else "partial",
        "full_protocol": full_protocol,
    }


def run_country(country: str, addresses: list[str] | None = None,
                terms: list[str] | None = None, skip_collect: bool = False,
                collect_only: bool = False, min_delay: float = 1.0,
                max_delay: float = 3.0, data_root: str | Path | None = None) -> dict:
    data_root = Path(data_root) if data_root else ROOT / "data"
    plan = plan_country(country, addresses, terms)
    run_token = _run_token()
    diagnostic_root = (data_root / country / "processed" / "diagnostic" / run_token
                       if not plan["full_protocol"] else None)
    sources = {}
    classifications = {}
    for zone in plan["addresses"]:
        slug = zone["slug"]
        raw_dir = data_root / country / "raw" / slug
        if skip_collect:
            source = _complete_source(raw_dir, country, slug, plan["queries"])
        else:
            source, _ = run_search(slug, plan["queries"], raw_dir, country=country,
                                   min_delay=min_delay, max_delay=max_delay)
        sources[slug] = str(source)
        if not collect_only:
            if diagnostic_root is not None:
                classification = diagnostic_root / "classifications" / f"{slug}.csv"
            else:
                classification = (data_root / country / "processed" / slug
                                  / f"classifications_{run_token}.csv")
            run_classify(str(source), str(classification), country=country)
            classifications[slug] = str(classification)
    result = {**plan, "derived_run_id": run_token, "sources": sources}
    if not collect_only:
        export_kwargs = {
            "addresses": list(sources),
            "data_root": data_root,
            "sources": sources,
            "classification_paths": classifications,
            "run_token": run_token,
        }
        if diagnostic_root is not None:
            export_kwargs["out_dir"] = str(diagnostic_root / "deliverable")
        deliverable = run_export(country, **export_kwargs)
        processed_manifest = _write_processed_manifest(
            country, plan, sources, classifications, deliverable, data_root,
        )
        result["classifications"] = classifications
        result["deliverable"] = {**deliverable,
                                 "manifest": str(processed_manifest)}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="run the four-market Rappi tobacco study")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--country", action="append", choices=COUNTRIES,
                       help="country code; repeat to run more than one")
    group.add_argument("--all-countries", action="store_true")
    parser.add_argument("--address", action="append",
                        help="zone slug; repeatable and valid with one country only")
    parser.add_argument("--terms", default=None, help="comma-separated query override")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate and print addresses, queries, and request counts")
    parser.add_argument("--skip-collect", action="store_true",
                        help="classify/export the latest successful search files")
    parser.add_argument("--collect-only", action="store_true",
                        help="collect raw search files without classification/export")
    parser.add_argument("--min-delay", type=float, default=1.0)
    parser.add_argument("--max-delay", type=float, default=3.0)
    args = parser.parse_args()
    countries = list(COUNTRIES) if args.all_countries else args.country
    if len(countries) != len(set(countries)):
        parser.error("each --country may be supplied only once")
    if args.address and len(countries) != 1:
        parser.error("--address requires exactly one --country")
    if args.skip_collect and args.collect_only:
        parser.error("--skip-collect and --collect-only cannot be used together")
    terms = ([term.strip() for term in args.terms.split(",") if term.strip()]
             if args.terms else None)
    if args.terms and not terms:
        parser.error("--terms must contain at least one query")
    if args.dry_run:
        result = [plan_country(code, args.address, terms) for code in countries]
    else:
        result = [run_country(
            code, addresses=args.address, terms=terms, skip_collect=args.skip_collect,
            collect_only=args.collect_only, min_delay=args.min_delay, max_delay=args.max_delay,
        ) for code in countries]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
