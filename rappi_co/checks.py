"""Fail-closed collection guardrails:
  - the delivery address was never actually set (auto-located generic centroid)
  - whole store types returned 0 stores (e.g. supermarkets/kioscos missing)
  - the catalog came back empty or truncated to one section

  RAPPI_ADDRESS=calle-19-centro python -m rappi_co.checks --stage all
  python -m rappi_co.checks --stage preflight        # config sanity, no address needed

exit code is nonzero if any check fails, so it doubles as a ci/pytest gate.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import yaml

from rappi_co import settings as S
from rappi_co.bootstrap import verify_locked

ROOT = S.PROJECT_ROOT
_FAILS: list[str] = []


def _fail(msg: str):
    _FAILS.append(msg)
    print("  FAIL:", msg, flush=True)


def _ok(msg: str):
    print("  ok:  ", msg, flush=True)


def _zones() -> list[dict]:
    from rappi_co.configs import load_zones
    return load_zones(ROOT / "config" / "zones_co.yml")


def _seed_types() -> list[str]:
    from rappi_co.configs import load_seed_paths
    seeds = load_seed_paths(ROOT / "config" / "seed_paths_co.yml")
    return [s["store_type"] for s in seeds]


def _search_terms() -> list[str]:
    cfg = yaml.safe_load((ROOT / "config" / "relevant_sections_co.yml").read_text(encoding="utf-8")) or {}
    return list(dict.fromkeys(t.strip() for t in (cfg.get("search_terms") or []) if t and t.strip()))


def _rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _store_types(row: dict) -> list[str]:
    # store_types is stored as a json-ish list string, e.g. '["market"]'.
    raw = (row.get("store_types") or "").strip("[]").replace('"', "")
    return [t.strip() for t in raw.split(",") if t.strip()]


def check_preflight():
    print("[preflight]")
    zones = _zones()
    for z in zones:
        lat, lng = float(z["lat"]), float(z["lng"])
        # rough bogotá bounding box — catch a bad/placeholder geocode.
        if not (3.5 < lat < 5.5 and -75.0 < lng < -73.5):
            _fail(f"{z['slug']}: coords {lat},{lng} are not in bogotá")
    _ok(f"{len(zones)} addresses, all with bogotá coords")
    _ok(f"{len(_seed_types())} store-type seeds configured: {_seed_types()}")


def check_bootstrap(address: str):
    print(f"[bootstrap] {address}")
    z = next((z for z in _zones() if z["slug"] == address), None)
    if not z:
        _fail(f"{address} not in zones_co.yml"); return
    state = ROOT / "data" / "state" / f"{address}.json"
    if not state.exists():
        _fail(f"no session file {state} — run `python -m rappi_co.bootstrap --address {address}`"); return
    ok, msg = verify_locked(state, float(z["lat"]), float(z["lng"]))
    (_ok if ok else _fail)(f"{address} location: {msg}")


def check_enumeration(address: str):
    print(f"[enumeration] {address}")
    raw = ROOT / "data" / "raw" / address
    files = sorted(raw.glob("stores_*.csv"))
    if not files:
        _fail(f"{address}: no stores_*.csv (run `scrapy crawl stores`)"); return
    rows = _rows(files[-1])
    if not rows:
        _fail(f"{address}: stores csv is empty"); return
    by_type = Counter(t for r in rows for t in _store_types(r))
    _ok(f"{address}: {len(rows)} stores; by seed {dict(by_type)}")
    # total-count sanity (a bogotá address should surface ~1,000+ retail stores; a tiny
    # number means the enumeration broke — the bespoke scraper's "4 stores" failure mode).
    if len(rows) < 500:
        _fail(f"{address}: only {len(rows)} stores — enumeration looks incomplete (expected ~1,000+)")
    # rappi can't filter by type (slugs collapse to one aggregate), so the real coverage test
    # is whether known supermarket / convenience / pharmacy chains actually show up.
    blob = " ".join(((r.get("name") or "") + " " + (r.get("slug") or "")).lower() for r in rows)
    expected = {
        "supermarket": ["exito", "carulla", "olimpica", "olímpica", "jumbo", "metro", "ara", "d1", "makro"],
        "convenience": ["oxxo", "justo", "supernow", "kiosco", "express"],
        "pharmacy": ["farmatodo", "cruz verde", "cruzverde", "drogueria", "droguería", "farmacia", "locatel"],
    }
    for label, needles in expected.items():
        present = [n for n in needles if n in blob]
        if present:
            _ok(f"{address}: {label} chains present ({present[:4]})")
        else:
            _fail(f"{address}: no {label} chains among {len(rows)} stores — coverage gap")


def check_crawl(address: str):
    print(f"[crawl] {address}")
    raw = ROOT / "data" / "raw" / address
    menu = sorted(raw.glob("menu_items_*.csv"))
    stores = sorted(raw.glob("stores_*.csv"))
    if not menu:
        _fail(f"{address}: no menu_items_*.csv (run `scrapy crawl menu`)"); return
    items = _rows(menu[-1])
    if not items:
        _fail(f"{address}: menu_items is empty"); return
    stores_with_items = len({r.get("store_id") for r in items})
    sections = len({r.get("menu_section") for r in items if r.get("menu_section")})
    n_stores = len({r.get("store_id") for r in _rows(stores[-1])}) if stores else 0
    _ok(f"{address}: {len(items)} items from {stores_with_items} stores, {sections} sections")
    if n_stores and stores_with_items / n_stores < 0.3:
        _fail(f"{address}: only {stores_with_items}/{n_stores} stores yielded items "
              f"— likely a mass silent-skip / early stall")
    if sections < 3:
        _fail(f"{address}: items span only {sections} section(s) — catalog likely truncated")


def check_search(address: str):
    print(f"[search] {address}")
    raw = ROOT / "data" / "raw" / address
    items = sorted(raw.glob("search_items_*.csv"))
    if not items:
        _fail(f"{address}: no search_items_*.csv (run `python -m rappi_co.collect.search`)"); return
    rows = _rows(items[-1])
    if not rows:
        _fail(f"{address}: search_items is empty"); return
    stores = {r.get("store_id") for r in rows}
    types = {r.get("store_type") for r in rows if r.get("store_type")}
    _ok(f"{address}: {len(rows)} search items across {len(stores)} stores, {len(types)} store types")
    # a broken endpoint/term set returns almost nothing — the sin categories are large in bogotá.
    if len(stores) < 5:
        _fail(f"{address}: search hit only {len(stores)} stores — endpoint/terms likely broken")
    # every configured seed term should surface at least one product; list any that returned none.
    got = Counter(r.get("source_term") for r in rows)
    configured = _search_terms()
    zero = [t for t in configured if got.get(t, 0) == 0]
    if configured and len(zero) > max(2, len(configured) // 5):
        _fail(f"{address}: {len(zero)}/{len(configured)} seed terms returned 0 rows "
              f"(endpoint issue?): {zero[:8]}")
    elif zero:
        _ok(f"{address}: {len(zero)} niche term(s) returned 0 rows (acceptable): {zero}")
    else:
        _ok(f"{address}: all {len(configured)} seed terms returned rows")


def check_union(address: str):
    print(f"[union] {address}")
    raw = ROOT / "data" / "raw" / address
    unified = sorted(raw.glob("menu_items_unified_*.csv"))
    reports = sorted(raw.glob("coverage_report_*.json"))
    if not unified:
        _fail(f"{address}: no menu_items_unified_*.csv (run `python -m rappi_co.collect.union`)"); return
    n_unified = len(_rows(unified[-1]))
    if not reports:
        _ok(f"{address}: unified catalog has {n_unified} items (no coverage report found)"); return
    rep = json.loads(reports[-1].read_text(encoding="utf-8"))
    c = rep.get("counts", {})
    _ok(f"{address}: unified {c.get('unified_items')} items / {c.get('unified_stores')} stores "
        f"(breadth {c.get('breadth_items')}, search {c.get('search_items')})")
    _ok(f"{address}: search surfaced {c.get('search_items_missing_from_crawl')} items + "
        f"{c.get('search_stores_missing_from_crawl')} stores the crawl missed (now ingested)")
    # the union must not lose breadth rows.
    if c.get("unified_items") and c.get("breadth_items") and c["unified_items"] < c["breadth_items"]:
        _fail(f"{address}: unified ({c['unified_items']}) < breadth ({c['breadth_items']}) — union dropped rows")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage",
                    choices=["all", "preflight", "bootstrap", "enum", "crawl", "search", "union"],
                    default="all")
    ap.add_argument("--address", default=S.ACTIVE_ZONE_SLUG)
    args = ap.parse_args()
    a = args.address
    if args.stage in ("all", "preflight"):
        check_preflight()
    if args.stage in ("all", "bootstrap"):
        check_bootstrap(a)
    if args.stage in ("all", "enum"):
        check_enumeration(a)
    if args.stage in ("all", "crawl"):
        check_crawl(a)
    if args.stage in ("all", "search"):
        check_search(a)
    if args.stage in ("all", "union"):
        check_union(a)
    print(f"\n{'ALL CHECKS PASSED' if not _FAILS else str(len(_FAILS)) + ' CHECK(S) FAILED'}")
    return 1 if _FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
