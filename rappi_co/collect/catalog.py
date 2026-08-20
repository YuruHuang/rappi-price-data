"""Collect full tobacco-aisle menu items via the catalog content API, per delivery address.

Complements the keyword search (which caps at 25/store/query) by walking each store's tobacco aisles to
every product. Reads the store list from the address's latest search_items (store_id + store_type), so
it reaches exactly the stores search surfaced -- including chains the storefront crawl never enumerated.
Output matches the search_items schema, so collect.union / union_zones fold it straight in.

run:  python -m rappi_co.collect.catalog --address calle-19-centro
"""
from __future__ import annotations

import argparse
import csv
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from rappi_co.collect.search import OUT_COLS, _zone
from rappi_co.extract.regex_enrich import enrich_item
from rappi_co.parsers.catalog_api import (
    AuthExpired, catalog_product_to_row, fetch_guest_credentials,
    iter_store_tobacco_products, _headers,
)
from rappi_co.pipelines import _serialize_for_csv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("collect.catalog")

ROOT = Path(__file__).resolve().parents[2]


def _store_list(search_items_path: Path) -> list[dict]:
    """Unique (store_id, store_type, parent_store_type, store_name) from an address's search output."""
    import pandas as pd
    df = pd.read_csv(search_items_path, dtype=str, keep_default_na=False)
    cols = [c for c in ("store_id", "store_type", "parent_store_type", "store_name") if c in df.columns]
    stores = df[cols].drop_duplicates("store_id")
    return stores.to_dict("records")


def run(address: str, out_dir: Path | None = None, delay: float = 0.4) -> Path:
    zone = _zone(address)
    lat, lng = float(zone["lat"]), float(zone["lng"])
    out_dir = out_dir or (ROOT / "data" / "raw" / address)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    items_path = out_dir / f"menu_items_{ts}.csv"
    work = items_path.with_suffix(".csv.partial")

    search_items = sorted((ROOT / "data" / "raw" / address).glob("search_items_*.csv"))
    if not search_items:
        raise SystemExit(f"no search_items for {address}; run rappi_co.collect.search first")
    stores = _store_list(search_items[-1])
    logger.info("catalog collection: address=%s (%.4f,%.4f) stores=%d", address, lat, lng, len(stores))

    storage_state = str(ROOT / "data" / "state" / f"{address}.json")
    creds = fetch_guest_credentials(storage_state, lat, lng)
    client = httpx.Client(timeout=40.0, headers=_headers(creds))

    seen: set[tuple[str, str]] = set()
    n_rows = 0
    stores_with_tobacco = 0
    with open(work, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS, extrasaction="ignore")
        w.writeheader()
        for i, st in enumerate(stores, 1):
            sid = st.get("store_id")
            stype = st.get("store_type") or ""
            parent = st.get("parent_store_type") or ""
            if not sid or not stype:
                continue
            for attempt in (1, 2):
                try:
                    products = iter_store_tobacco_products(client, sid, stype, parent, lat, lng)
                    break
                except AuthExpired:
                    logger.info("guest token expired; refreshing")
                    client.close()
                    creds = fetch_guest_credentials(storage_state, lat, lng)
                    client = httpx.Client(timeout=40.0, headers=_headers(creds))
            else:
                products = {}
            meta = {"store_id": sid, "store_type": stype, "parent_store_type": parent,
                    "store_name": st.get("store_name")}
            wrote = 0
            for prod in products.values():
                row = catalog_product_to_row(prod, meta, f"catalog?store={sid}")
                if not row:
                    continue
                key = (str(row["store_id"]), str(row["product_id"]))
                if key in seen:
                    continue
                seen.add(key)
                row = enrich_item(row)
                row["scrape_timestamp"] = ts
                w.writerow({c: _serialize_for_csv(row.get(c)) for c in OUT_COLS})
                n_rows += 1
                wrote += 1
            if wrote:
                stores_with_tobacco += 1
                logger.info("  [%3d/%d] %-28s +%d products", i, len(stores),
                            (st.get("store_name") or stype)[:28], wrote)
            if i % 20 == 0:
                f.flush()
            if delay > 0:
                time.sleep(delay)

    client.close()
    work.replace(items_path)
    logger.info("wrote %d catalog menu items from %d tobacco-carrying stores -> %s",
                n_rows, stores_with_tobacco, items_path)
    return items_path


def main() -> int:
    p = argparse.ArgumentParser(description="collect tobacco-aisle menu items via the catalog API")
    p.add_argument("--address", required=True, help="zone slug from config/zones_co.yml")
    p.add_argument("--out", default=None, help="output dir (default data/raw/<address>/)")
    p.add_argument("--delay", type=float, default=0.4, help="seconds between stores")
    a = p.parse_args()
    run(a.address, Path(a.out) if a.out else None, a.delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
