"""Attribute the single breadth crawl to each address, then union it with that address's search.

The breadth crawl (see merge_stores) fetches every unique store once. A store's products belong to
each address whose search surfaced it -- its discovery_zones. For every address this filters the
combined menu_items down to that address's stores, then reuses collect.union to merge the slice with
the address's search_items: search keeps its per-address price on any overlap, and breadth-only rows
are added. The result, data/raw/<zone>/menu_items_unified_<ts>.csv, is what release/export then build
from.

    python -m rappi_co.collect.union_zones \
        --stores data/raw/_all/stores_all_<ts>.csv \
        --menu   data/raw/calle-19-centro/menu_items_<ts>.csv
"""
from __future__ import annotations

import argparse
import csv
import glob
import logging
from datetime import datetime, timezone
from pathlib import Path

from rappi_co.collect import union as union_mod
from rappi_co.collect.merge_stores import _parse_list
from rappi_co.configs import load_zones

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("collect.union_zones")

ROOT = Path(__file__).resolve().parents[2]


def _zone_store_ids(stores_all_path: str | Path, zone: str) -> set[str]:
    """store_ids whose discovery_zones include this address (the stores it can order from)."""
    ids: set[str] = set()
    with open(stores_all_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if zone in _parse_list(row.get("discovery_zones")):
                sid = str(row.get("store_id") or "")
                if sid:
                    ids.add(sid)
    return ids


def _write_zone_menu(menu_all_path: str | Path, store_ids: set[str], out_path: Path) -> int:
    import pandas as pd
    menu = pd.read_csv(menu_all_path, dtype=str, keep_default_na=False)
    kept = menu[menu["store_id"].astype(str).isin(store_ids)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    kept.to_csv(out_path, index=False, encoding="utf-8-sig")
    return len(kept)


def _latest(pattern: str) -> str | None:
    hits = sorted(glob.glob(pattern))
    return hits[-1] if hits else None


def union_zones(zone_slugs: list[str], stores_all_path: str | Path,
                menu_all_path: str | Path) -> dict[str, dict]:
    """Per address: filter the breadth menu to its stores and union with its search_items."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results: dict[str, dict] = {}
    for zone in zone_slugs:
        raw = ROOT / "data" / "raw" / zone
        search = _latest(str(raw / "search_items_*.csv"))
        if not search:
            raise SystemExit(f"no search_items_*.csv for {zone}; run rappi_co.collect.search first")
        store_ids = _zone_store_ids(stores_all_path, zone)
        breadth = raw / f"menu_items_breadth_{ts}.csv"
        n_breadth = _write_zone_menu(menu_all_path, store_ids, breadth)
        unified_out = raw / f"menu_items_unified_{ts}.csv"
        unified_path, report_path = union_mod.run(zone, str(breadth), search, str(unified_out))
        results[zone] = {
            "stores_for_zone": len(store_ids),
            "breadth_rows_for_zone": n_breadth,
            "unified": unified_path,
            "coverage_report": report_path,
        }
        logger.info("%s: %d stores, %d breadth rows -> %s", zone, len(store_ids), n_breadth, unified_path)
    return results


def main() -> int:
    ap = argparse.ArgumentParser(
        description="attribute the combined breadth crawl per address and union with search")
    ap.add_argument("--stores", required=True, help="stores_all_*.csv from merge_stores")
    ap.add_argument("--menu", required=True, help="combined menu_items_*.csv from the single menu crawl")
    ap.add_argument("--zone", action="append", default=[],
                    help="zone slug (repeatable; default: every zone in zones_co.yml)")
    args = ap.parse_args()
    zones = args.zone or [z["slug"] for z in load_zones(ROOT / "config" / "zones_co.yml")]
    union_zones(zones, args.stores, args.menu)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
