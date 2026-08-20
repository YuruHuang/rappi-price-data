"""Union the breadth crawl (menu_items) with the search collection (search_items) for an address,
dedup by (store_id, product_id), and emit the search-coverage audit.

search rows win on a key collision (they carry the richer signals); breadth-only items keep their
real aisle section. the coverage report lists what search surfaced that the crawl missed — stores and
items — which is the explicit answer to "did we capture everything search sees?".

run:  python -m rappi_co.collect.union --address calle-19-centro
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from rappi_co.collect.search import OUT_COLS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("collect.union")

ROOT = Path(__file__).resolve().parents[2]


def _latest(pattern: str, exclude: str | None = None) -> str | None:
    hits = sorted(f for f in glob.glob(pattern) if not (exclude and exclude in f))
    return hits[-1] if hits else None


def _key(df: pd.DataFrame) -> pd.Series:
    return df["store_id"].astype(str) + "|" + df["product_id"].astype(str)


def run(address: str, menu_path: str | None, search_path: str | None,
        out_path: str | None) -> tuple[str, str]:
    raw = ROOT / "data" / "raw" / address
    # breadth file is menu_items_<ts>.csv — exclude our own menu_items_unified_* outputs.
    menu_path = menu_path or _latest(str(raw / "menu_items_*.csv"), exclude="unified")
    search_path = search_path or _latest(str(raw / "search_items_*.csv"))
    if not menu_path:
        raise SystemExit(f"no breadth menu_items_*.csv in {raw}")
    if not search_path:
        raise SystemExit(f"no search_items_*.csv in {raw} (run rappi_co.collect.search first)")

    mb = pd.read_csv(menu_path, dtype=str, keep_default_na=False, na_values=[""])
    ms = pd.read_csv(search_path, dtype=str, keep_default_na=False, na_values=[""])
    if "source" not in mb.columns:
        mb["source"] = "crawl"
    mb["source"] = mb["source"].fillna("crawl")
    logger.info("breadth=%d rows (%s)  search=%d rows (%s)",
                len(mb), Path(menu_path).name, len(ms), Path(search_path).name)

    mb["_key"], ms["_key"] = _key(mb), _key(ms)
    # search first so drop_duplicates(keep=first) lets search win on a collision.
    combined = pd.concat([ms, mb], ignore_index=True, sort=False)
    unified = combined.drop_duplicates(subset="_key", keep="first").copy()

    # Carry the catalog/menu side's real store aisle onto every catalog-covered product -- even the ones
    # where search won the price on a collision -- so the store's own authoritative aisle survives the
    # dedup. The classifier trusts this (not search's mis-shelving category bucket) to promote nicotine
    # products the name-only lexicon misses; see stage_c_overrides catalog-aisle promotion.
    if "menu_section" in mb.columns:
        cat_aisle = mb.drop_duplicates("_key", keep="first").set_index("_key")["menu_section"]
        unified["catalog_menu_section"] = unified["_key"].map(cat_aisle).fillna("")

    # column order: the search superset, then any breadth-only columns, minus the helper key.
    cols = [c for c in OUT_COLS if c in unified.columns]
    cols += [c for c in unified.columns if c not in cols and c != "_key"]
    unified = unified[cols]

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = out_path or str(raw / f"menu_items_unified_{ts}.csv")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    unified.to_csv(out_path, index=False, encoding="utf-8-sig")

    # --- coverage audit ---
    bkeys, skeys = set(mb["_key"]), set(ms["_key"])
    bstores = set(mb["store_id"].astype(str))
    sstores = set(ms["store_id"].astype(str))
    missing_items = skeys - bkeys
    missing_stores = sstores - bstores
    st_by_store = (ms.drop_duplicates("store_id")
                     .set_index(ms.drop_duplicates("store_id")["store_id"].astype(str)))
    missing_store_detail = [
        {"store_id": s,
         "store_type": (st_by_store.loc[s, "store_type"] if s in st_by_store.index else None),
         "store_name": (st_by_store.loc[s, "store_name"] if s in st_by_store.index else None)}
        for s in sorted(missing_stores)
    ]
    report = {
        "address": address,
        "generated_at": ts,
        "breadth_file": Path(menu_path).name,
        "search_file": Path(search_path).name,
        "unified_file": Path(out_path).name,
        "counts": {
            "breadth_items": len(mb), "search_items": len(ms), "unified_items": len(unified),
            "breadth_stores": len(bstores), "search_stores": len(sstores),
            "unified_stores": unified["store_id"].astype(str).nunique(),
            "search_items_missing_from_crawl": len(missing_items),
            "search_stores_missing_from_crawl": len(missing_stores),
        },
        "search_store_types": ms.dropna(subset=["store_type"])["store_type"].value_counts().to_dict()
                              if "store_type" in ms.columns else {},
        "surfaced_but_missing_stores": missing_store_detail[:200],
    }
    report_path = str(raw / f"coverage_report_{ts}.json")
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    c = report["counts"]
    logger.info("unified: %d items / %d stores  (breadth %d, search %d)",
                c["unified_items"], c["unified_stores"], c["breadth_items"], c["search_items"])
    logger.info("search surfaced %d items and %d stores the crawl MISSED",
                c["search_items_missing_from_crawl"], c["search_stores_missing_from_crawl"])
    logger.info("wrote %s + %s", Path(out_path).name, Path(report_path).name)
    return out_path, report_path


def main() -> int:
    p = argparse.ArgumentParser(description="union breadth + search into one deduped catalog + audit")
    p.add_argument("--address", required=True)
    p.add_argument("--menu", default=None, help="breadth menu_items csv (default: latest)")
    p.add_argument("--search", default=None, help="search_items csv (default: latest)")
    p.add_argument("--out", default=None)
    a = p.parse_args()
    run(a.address, a.menu, a.search, a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
