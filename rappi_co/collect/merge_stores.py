"""Merge per-address store enumerations into one deduped list for a single menu crawl.

Each address's `scrapy crawl stores` writes data/raw/<zone>/stores_*.csv, tagging every storefront
with discovery_zones=[<zone>]. This unions those files by store_id -- so a store reachable from
several addresses lists all of them in discovery_zones -- and writes data/raw/_all/stores_all_<ts>.csv.
That merged file is the single input the menu crawl reads, so each unique store's catalog is fetched
exactly once instead of re-crawled per address.

    python -m rappi_co.collect.merge_stores                 # all configured zones
    python -m rappi_co.collect.merge_stores --zone calle-19-centro --zone carrera-108-fontibon
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from rappi_co.configs import load_zones
from rappi_co.pipelines import CsvWriterPipeline, _serialize_for_csv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("collect.merge_stores")

ROOT = Path(__file__).resolve().parents[2]
STORE_COLUMNS = CsvWriterPipeline.STORE_COLUMNS
_LIST_COLUMNS = ("store_types", "discovery_paths", "discovery_zones")


def _parse_list(value) -> list[str]:
    """Read a '|'-free JSON list cell back into a Python list (tolerating a bare scalar)."""
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return [str(value)]
    return [str(x) for x in parsed] if isinstance(parsed, list) else [str(parsed)]


def _largest_stores_csv(zone_dir: Path) -> Path | None:
    # The largest stores_*.csv is the full enumeration; the menu run re-emits a smaller one.
    files = list(zone_dir.glob("stores_*.csv"))
    return max(files, key=lambda p: p.stat().st_size) if files else None


def merge_stores(zone_slugs: list[str], out_dir: Path | None = None) -> Path:
    """Union each zone's largest store enumeration into one deduped stores_all_<ts>.csv."""
    merged: dict[str, dict] = {}
    inputs = 0
    for slug in zone_slugs:
        path = _largest_stores_csv(ROOT / "data" / "raw" / slug)
        if not path:
            logger.warning("no stores_*.csv for %s -- did `scrapy crawl stores` run for it?", slug)
            continue
        inputs += 1
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                sid = row.get("store_id")
                if not sid:
                    continue
                # If a file predates zone tagging, attribute it to the slug it was read from.
                zones = _parse_list(row.get("discovery_zones")) or [slug]
                lists = {c: _parse_list(row.get(c)) for c in _LIST_COLUMNS}
                lists["discovery_zones"] = zones
                existing = merged.get(sid)
                if existing is None:
                    merged[sid] = {**row, **{c: list(dict.fromkeys(v)) for c, v in lists.items()}}
                    continue
                for col, vals in lists.items():
                    existing[col] = list(dict.fromkeys((existing.get(col) or []) + vals))
                for col in STORE_COLUMNS:
                    if col not in _LIST_COLUMNS and not existing.get(col) and row.get(col):
                        existing[col] = row[col]
        logger.info("read %s", path)

    if not merged:
        raise SystemExit("no store rows to merge; run `scrapy crawl stores` per address first")

    out_dir = out_dir or (ROOT / "data" / "raw" / "_all")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"stores_all_{ts}.csv"
    work = out_path.with_suffix(".csv.partial")
    with open(work, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=STORE_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for row in merged.values():
            w.writerow({c: _serialize_for_csv(row.get(c)) for c in STORE_COLUMNS})
    work.replace(out_path)

    multi = sum(1 for r in merged.values() if len(r["discovery_zones"]) > 1)
    logger.info("merged %d store file(s) -> %d unique stores (%d reachable from >1 address) -> %s",
                inputs, len(merged), multi, out_path)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="merge per-address store enumerations into one deduped list")
    ap.add_argument("--zone", action="append", default=[],
                    help="zone slug (repeatable; default: every zone in zones_co.yml)")
    ap.add_argument("--out", default=None, help="output dir (default data/raw/_all/)")
    args = ap.parse_args()
    zones = args.zone or [z["slug"] for z in load_zones(ROOT / "config" / "zones_co.yml")]
    merge_stores(zones, Path(args.out) if args.out else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
