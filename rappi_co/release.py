"""Fail-closed two-location release pipeline.

Collects, validates, classifies, exports, verifies, and atomically publishes the
configured Bogotá locations. Use --skip-collect only to rebuild from existing raw
search files produced by a successful collection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from rappi_co.classify.run import run_classify
from rappi_co.collect.search import _terms, run as run_search
from rappi_co.configs import load_zones
from rappi_co.export.tobacco_deliverable import run_export
from rappi_co.qc.gate import run_qc

ROOT = Path(__file__).resolve().parents[1]
GOLD_FILES = [
    ROOT / "rappi_co" / "qc" / "gold" / "tobacco_gold_co.csv",
    ROOT / "rappi_co" / "qc" / "gold" / "tobacco_gold_co_adversarial.csv",
]


def _latest(directory: Path, pattern: str) -> Path:
    files = sorted(directory.glob(pattern))
    if not files:
        raise FileNotFoundError(f"no {pattern} in {directory}")
    return files[-1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_source(path: Path, address: str) -> dict:
    """Validate the per-address collection source (search only, or the search+breadth union)."""
    rows = pd.read_csv(path, dtype=str, keep_default_na=False)
    if rows.empty:
        raise ValueError(f"{address}: collection source is empty")
    required = {"store_id", "product_id", "name", "price_cop", "source_term"}
    missing = required - set(rows.columns)
    if missing:
        raise ValueError(f"{address}: collection source lacks {sorted(missing)}")
    if rows.duplicated(["store_id", "product_id"]).any():
        raise ValueError(f"{address}: duplicate source product keys")
    stores = rows["store_id"].nunique()
    if stores < 5:
        raise ValueError(f"{address}: only {stores} stores; collection appears incomplete")
    # The search rows still carry every seed term (breadth rows add blank source_term); a large gap
    # means the search side is broken, not merely that the crawl added term-less rows.
    configured_terms = set(_terms(None))
    observed_terms = set(rows["source_term"])
    if len(configured_terms - observed_terms) > max(2, len(configured_terms) // 5):
        raise ValueError(f"{address}: too many seed terms returned no products")
    return {"rows": len(rows), "stores": stores, "terms": len(observed_terms & configured_terms)}


def _verify_export(result: dict, expected_zones: list[str]) -> dict:
    from openpyxl import load_workbook

    items_path = Path(result["items_csv"])
    stores_path = Path(result["stores_csv"])
    workbook_path = Path(result["xlsx"])
    items = pd.read_csv(items_path, dtype=str, keep_default_na=False)
    stores = pd.read_csv(stores_path, dtype=str, keep_default_na=False)
    observed = sorted(set(items["zone_slug"]))
    if observed != sorted(expected_zones):
        raise ValueError(f"final location mismatch: expected {expected_zones}, got {observed}")
    if items.duplicated(["zone_slug", "store_id", "product_id"]).any():
        raise ValueError("final items contain duplicate location/store/product observations")
    if (items["product_type"].str.strip() == "").any():
        raise ValueError("final items contain blank product types")
    if items["flags"].str.lower().eq("nan").any():
        raise ValueError("final items contain literal nan flags")
    wb = load_workbook(workbook_path, read_only=True, data_only=False)
    expected_sheets = {"items", "stores", "paraphernalia_oos", "review_candidates",
                       "locations", "summary", "data_dictionary"}
    if set(wb.sheetnames) != expected_sheets:
        raise ValueError(f"workbook sheets differ: {wb.sheetnames}")
    if wb["items"].max_row - 1 != len(items) or wb["stores"].max_row - 1 != len(stores):
        raise ValueError("CSV and workbook row counts differ")
    wb.close()
    return {
        "items": len(items),
        "store_observations": len(stores),
        "locations": observed,
        "items_by_location": items.groupby("zone_slug").size().astype(int).to_dict(),
    }


def _atomic_copy(source: Path, destination: Path) -> None:
    work = destination.with_name(destination.name + ".tmp")
    shutil.copy2(source, work)
    work.replace(destination)


def build_release(skip_collect: bool = False, publish: bool = True) -> dict:
    zones = load_zones(ROOT / "config" / "zones_co.yml")
    if len(zones) != 2:
        raise ValueError(f"two-location release requires exactly 2 configured zones, got {len(zones)}")
    slugs = [zone["slug"] for zone in zones]
    source_files: dict[str, Path] = {}
    coverage = {}

    for slug in slugs:
        raw_dir = ROOT / "data" / "raw" / slug
        if skip_collect:
            search_path = _latest(raw_dir, "search_items_*.csv")
        else:
            search_path, _ = run_search(slug, _terms(None), raw_dir)
        # Build from the search+breadth union when it exists (produced by collect.union after the
        # breadth crawl); otherwise from search alone. Same file feeds classify and export.
        unified = sorted(raw_dir.glob("menu_items_unified_*.csv"))
        source_path = unified[-1] if unified else search_path
        coverage[slug] = _validate_source(source_path, slug)
        source_files[slug] = source_path

        classification = ROOT / "data" / "co" / "processed" / slug / "classifications.csv"
        run_classify(str(source_path), str(classification))

    gates = {}
    for gold in GOLD_FILES:
        result = run_qc(gold_path=str(gold))
        if result["gate"] != "PASS":
            raise ValueError(f"quality gate failed for {gold.name}: {result['metrics']}")
        gates[gold.name] = result["metrics"]

    export = run_export(addresses=slugs, out_dir=str(ROOT / "data" / "co" / "processed" / "combined"))
    verification = _verify_export(export, slugs)

    generated_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "generated_at_utc": generated_at,
        "locations": zones,
        "coverage": coverage,
        "quality_gates": gates,
        "verification": verification,
        "source_files": {slug: {"file": path.name, "sha256": _sha256(path)}
                         for slug, path in source_files.items()},
    }

    if publish:
        destination = ROOT / "deliverables" / "two-locations"
        destination.mkdir(parents=True, exist_ok=True)
        outputs = {
            "tobacco_items.csv": Path(export["items_csv"]),
            "tobacco_stores.csv": Path(export["stores_csv"]),
            "tobacco_master.xlsx": Path(export["xlsx"]),
        }
        for name, source in outputs.items():
            _atomic_copy(source, destination / name)

        locations = pd.DataFrame(zones).rename(columns={"lat": "latitude", "lng": "longitude"})
        counts = pd.Series(verification["items_by_location"], name="n_tobacco_observations")
        locations = locations.merge(counts, left_on="slug", right_index=True, how="left")
        locations_work = destination / "locations.csv.tmp"
        locations.to_csv(locations_work, index=False, encoding="utf-8-sig")
        locations_work.replace(destination / "locations.csv")

        manifest["published_files"] = {}
        for path in sorted(destination.glob("*")):
            if path.name == "manifest.json" or path.name.endswith(".tmp"):
                continue
            manifest["published_files"][path.name] = {
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        manifest_work = destination / "manifest.json.tmp"
        manifest_work.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        manifest_work.replace(destination / "manifest.json")

    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="build and verify the two-location release")
    parser.add_argument("--skip-collect", action="store_true",
                        help="rebuild from the latest successful raw search files")
    parser.add_argument("--no-publish", action="store_true",
                        help="verify outputs under data/ without updating deliverables/")
    args = parser.parse_args()
    result = build_release(skip_collect=args.skip_collect, publish=not args.no_publish)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
