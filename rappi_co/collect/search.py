"""Search-driven depth and coverage collection (tokenless unified-search).

Legacy mode reads the Colombia search terms and locations shipped with the original release.
Country mode (``--country``) reads the fixed generic and brand-qualified queries from
config/study/, while keeping collection address-specific and country-aware.

run:  python -m rappi_co.collect.search --country ar --address centro-galerias-pacifico
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import logging
import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

from rappi_co.configs import load_study_profile, study_queries
from rappi_co.extract.regex_enrich import enrich_item
from rappi_co.parsers.search_api import (
    SEARCH_URL,
    STUDY_SEARCH_PATH,
    _HEADERS,
    iter_products,
    search,
    search_product_to_row,
    validate_search_payload,
)
from rappi_co.pipelines import CsvWriterPipeline, _serialize_for_csv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("collect.search")

ROOT = Path(__file__).resolve().parents[2]  # repo root
STUDY_CONFIG = ROOT / "config" / "study"
EXTRA_COLS = ["store_type", "store_name", "parent_store_type", "ean", "alcoholic_beverage",
              "restriction_tag", "requires_medical_prescription", "source_term", "source"]
OUT_COLS = CsvWriterPipeline.MENU_COLUMNS + EXTRA_COLS
STUDY_EXTRA_COLS = ["country_code", "country", "city", "currency", "price_local",
                    "original_price_local", "unit_price_local", "source_terms"]
STUDY_OUT_COLS = OUT_COLS + STUDY_EXTRA_COLS
STORE_COLS = ["store_id", "store_type", "store_name", "parent_store_type", "n_products", "terms"]


def _profile(country: str, locations_file: str | Path | None = None) -> dict:
    return load_study_profile(country, STUDY_CONFIG, locations_file=locations_file)


def _zone(address: str, country: str | None = None,
          locations_file: str | Path | None = None) -> dict:
    if country:
        profile = _profile(country, locations_file)
        zones = profile["zones"]
        source = str(locations_file) if locations_file else f"config/study/zones_{country}.yml"
    else:
        zones = (yaml.safe_load((ROOT / "config" / "zones_co.yml").read_text(encoding="utf-8"))
                 or {}).get("zones") or []
        source = "config/zones_co.yml"
    for z in zones:
        if z["slug"] == address:
            return z
    raise SystemExit(f"address {address!r} not in {source} (have: "
                     f"{[z['slug'] for z in zones]})")


def _terms(explicit: str | None, country: str | None = None) -> list[str]:
    if explicit:
        return [t.strip() for t in explicit.split(",") if t.strip()]
    if country:
        return study_queries(_profile(country))
    cfg = yaml.safe_load((ROOT / "config" / "relevant_sections_co.yml").read_text(encoding="utf-8")) or {}
    seeds = cfg.get("search_terms") or []
    # de-dup, keep order
    return list(dict.fromkeys(t.strip() for t in seeds if t and t.strip()))


def _rewrite_source_terms(path: Path, rewritten: Path,
                          item_terms: dict[tuple[str, str], list[str]]) -> None:
    with open(path, encoding="utf-8-sig", newline="") as source, \
            open(rewritten, "w", encoding="utf-8-sig", newline="") as destination:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(destination, fieldnames=reader.fieldnames or [])
        writer.writeheader()
        for row in reader:
            key = (str(row["store_id"]), str(row["product_id"]))
            row["source_terms"] = "|".join(item_terms.get(key, [row.get("source_term", "")]))
            writer.writerow(row)


def run(address: str, terms: list[str], out_dir: Path,
        min_delay: float = 1.0, max_delay: float = 3.0,
        country: str | None = None,
        locations_file: str | Path | None = None) -> tuple[Path, Path]:
    if (not math.isfinite(min_delay) or not math.isfinite(max_delay)
            or min_delay < 0 or max_delay < min_delay):
        raise ValueError("delays must satisfy finite 0 <= min_delay <= max_delay")
    if locations_file is not None and not country:
        raise ValueError("locations_file requires a country")
    locations_path = Path(locations_file).resolve() if locations_file is not None else None
    locations_digest = (hashlib.sha256(locations_path.read_bytes()).hexdigest()
                        if locations_path is not None else None)
    profile = _profile(country, locations_file) if country else None
    zone = _zone(address, country, locations_file)
    lat, lng = float(zone["lat"]), float(zone["lng"])
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    items_path = out_dir / f"search_items_{ts}.csv"
    stores_path = out_dir / f"search_stores_{ts}.csv"
    raw_dir = out_dir / f"search_raw_{ts}"
    items_work = items_path.with_suffix(".csv.partial")
    stores_work = stores_path.with_suffix(".csv.partial")
    raw_work = out_dir / f"search_raw_{ts}.partial"
    rewritten_work = out_dir / f"search_items_{ts}.terms.partial"
    manifest_path = out_dir / f"search_manifest_{ts}.json"
    manifest_work = out_dir / f"search_manifest_{ts}.json.partial"
    staged_paths = [items_path, stores_path, raw_dir, items_work, stores_work, raw_work]
    if profile:
        staged_paths.extend([rewritten_work, manifest_path, manifest_work])
    if any(path.exists() for path in staged_paths):
        raise FileExistsError(f"timestamped collection paths already exist for {ts}")
    raw_work.mkdir(parents=True, exist_ok=False)

    seen: set[tuple[str, str]] = set()
    item_terms: dict[tuple[str, str], list[str]] = {}
    stores: dict[str, dict] = {}
    term_results: list[dict] = []
    n_rows = 0
    returned_product_count = 0
    if profile:
        logger.info("search collection: country=%s address=%s (%.4f,%.4f) terms=%d",
                    profile["country_code"], address, lat, lng, len(terms))
        headers = {**_HEADERS, "AUTH_USER": "-1",
                   "accept-language": profile["locale"],
                   "language": profile["locale"].split("-", 1)[0]}
        search_url = f"{profile['services_url'].rstrip('/')}{STUDY_SEARCH_PATH}"
        out_cols = STUDY_OUT_COLS
    else:
        logger.info("search collection: address=%s (%.4f,%.4f) terms=%d",
                    address, lat, lng, len(terms))
        headers = _HEADERS
        search_url = SEARCH_URL
        out_cols = OUT_COLS
    with httpx.Client(timeout=30.0, headers=headers) as client, \
            open(items_work, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out_cols, extrasaction="ignore")
        w.writeheader()
        for i, term in enumerate(terms, 1):
            if profile:
                resp = search(term, lat, lng, client=client, url=search_url)
            else:
                resp = search(term, lat, lng, client=client)
            validate_search_payload(resp, term)
            for group in resp["stores"]:
                if (not isinstance(group, dict)
                        or not isinstance(group.get("products", []), (list, type(None)))):
                    raise RuntimeError(f"search {term!r} returned malformed store/product groups; stop and inspect the response")
            # Persist the raw response so any field can be re-parsed later without re-scraping.
            _safe = "".join(c if c.isalnum() else "_" for c in term).strip("_") or "q"
            raw_name = f"{i:03d}_{_safe}.json.gz" if profile else f"{_safe}.json.gz"
            with gzip.open(raw_work / raw_name, "wt", encoding="utf-8") as rf:
                json.dump(resp, rf, ensure_ascii=False)
            term_rows = 0
            for meta, prod in iter_products(resp):
                returned_product_count += 1
                source_url = search_url if profile else f"unified-search?query={term}"
                row = search_product_to_row(meta, prod, term, source_url)
                if not row:
                    continue
                if profile:
                    is_cop = profile["currency"] == "COP"
                    row.update({
                        "country_code": profile["country_code"],
                        "country": profile["name"],
                        "city": zone.get("city", profile["city"]),
                        "currency": profile["currency"],
                        "price_local": row.get("price_cop"),
                        "original_price_local": row.get("original_price_cop"),
                        "unit_price_local": row.get("unit_price_cop") if is_cop else None,
                        "source_terms": term,
                    })
                    if not is_cop:
                        row["price_cop"] = None
                        row["original_price_cop"] = None
                        row["unit_price_cop"] = None
                key = (str(row["store_id"]), str(row["product_id"]))
                surfaced_by = item_terms.setdefault(key, [])
                if term not in surfaced_by:
                    surfaced_by.append(term)
                # accumulate store coverage even on dup (which terms surfaced the store)
                sid = str(row["store_id"])
                st = stores.setdefault(sid, {"store_id": sid, "store_type": row.get("store_type"),
                                             "store_name": row.get("store_name"),
                                             "parent_store_type": row.get("parent_store_type"),
                                             "n_products": 0, "terms": set()})
                st["terms"].add(term)
                if key in seen:
                    continue
                seen.add(key)
                st["n_products"] += 1
                row = enrich_item(row)
                row["scrape_timestamp"] = ts
                w.writerow({c: _serialize_for_csv(row.get(c)) for c in out_cols})
                n_rows += 1
                term_rows += 1
            logger.info("  [%2d/%d] %-24s +%d new (%d total)", i, len(terms), term, term_rows, n_rows)
            term_results.append({"query": term, "new_items": term_rows,
                                 "raw_file": raw_name})
            if i % 20 == 0:
                f.flush()
            if max_delay > 0:
                time.sleep(random.uniform(min_delay, max_delay))

    if profile:
        _rewrite_source_terms(items_work, rewritten_work, item_terms)
        rewritten_work.replace(items_work)

    with open(stores_work, "w", encoding="utf-8-sig", newline="") as sf:
        sw = csv.DictWriter(sf, fieldnames=STORE_COLS, extrasaction="ignore")
        sw.writeheader()
        for st in sorted(stores.values(), key=lambda s: s["n_products"], reverse=True):
            sw.writerow({**st, "terms": "|".join(sorted(st["terms"]))})

    if not seen and returned_product_count:
        raise RuntimeError(f"search collection for {address} returned products but none had usable identifiers; stop and inspect the response")
    if not seen:
        logger.warning("No listings returned for %s; preserving the completed empty search and its raw evidence", address)
    if (locations_path is not None
            and hashlib.sha256(locations_path.read_bytes()).hexdigest() != locations_digest):
        raise RuntimeError("locations file changed during collection; rerun after edits finish")
    items_work.replace(items_path)
    stores_work.replace(stores_path)
    raw_work.replace(raw_dir)

    if profile:
        manifest = {
            "schema_version": 1,
            "complete": True,
            "country_code": profile["country_code"],
            "address": address,
            "city": zone.get("city", profile["city"]),
            "address_label": zone.get("address", ""),
            "district": zone.get("district", ""),
            "latitude": lat,
            "longitude": lng,
            "currency": profile["currency"],
            "search_url": search_url,
            "queries": terms,
            "request_count": len(terms),
            "items": items_path.name,
            "stores": stores_path.name,
            "raw_directory": raw_dir.name,
            "n_items": n_rows,
            "n_stores": len(stores),
            "collection_outcome": "listings_returned" if seen else "no_results",
            "warnings": ([] if seen else ["No listings returned for this location and query plan; this does not establish product absence or confirm delivery coverage."]),
            "term_results": term_results,
            "timestamp_utc": ts,
        }
        if locations_file is not None:
            manifest["locations_file"] = {
                "path": str(locations_path),
                "sha256": locations_digest,
            }
        with open(manifest_work, "w", encoding="utf-8") as mf:
            json.dump(manifest, mf, ensure_ascii=False, indent=2)
            mf.write("\n")
        manifest_work.replace(manifest_path)

    logger.info("wrote %d search items across %d stores -> %s", n_rows, len(stores), items_path)
    logger.info("wrote %d stores -> %s", len(stores), stores_path)
    return items_path, stores_path


def main() -> int:
    p = argparse.ArgumentParser(description="collect relevant products via unified-search")
    p.add_argument("--country", choices=["ar", "co", "pe", "mx"], default=None,
                   help="collection country; omit for the earlier Colombia config")
    p.add_argument("--address", required=True, help="zone slug from the selected config")
    p.add_argument("--locations-file", type=Path,
                   help="CSV or YAML delivery locations; requires --country")
    p.add_argument("--terms", default=None, help="comma-separated override of the seed terms")
    p.add_argument("--out", default=None, help="output dir (default data/raw/<address>/)")
    p.add_argument("--min-delay", type=float, default=1.0, help="min seconds between term requests")
    p.add_argument("--max-delay", type=float, default=3.0, help="max seconds between term requests")
    a = p.parse_args()
    if a.locations_file is not None and not a.country:
        p.error("--locations-file requires --country")
    default_out = (ROOT / "data" / a.country / "raw" / a.address if a.country
                   else ROOT / "data" / "raw" / a.address)
    out_dir = Path(a.out) if a.out else default_out
    run(a.address, _terms(a.terms, a.country), out_dir,
        min_delay=a.min_delay, max_delay=a.max_delay, country=a.country,
        locations_file=a.locations_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
