"""Stage 2: per-store menu crawl.

reads the largest data/raw/<addr>/stores_*.csv (the full enumeration), fetches each
store's landing page to:
  (a) extract address fields and emit an updated Store record (the pipeline merges into
      the existing entry by store_id),
  (b) parse landing-page products,
  (c) extract aisle urls from aisles_tree_response and queue them.
each aisle subpage is then fetched and parsed for more products.

Pages render in a headless browser: www.rappi.com.co sits behind Cloudflare, which 403s plain HTTP,
so each landing/aisle is fetched with Playwright and the server-rendered __NEXT_DATA__ is read from
the rendered HTML. This is slower than a plain GET, so run it gently (raise DOWNLOAD_DELAY).

run:
    scrapy crawl menu                                       # full
    scrapy crawl menu -a stores=ID1,ID2 -a max_per_store=50 # smoke
    scrapy crawl menu -s DOWNLOAD_DELAY=5                    # extra gentle
"""
from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

import scrapy
from scrapy_playwright.page import PageMethod

from rappi_co.parsers.store_payload import (
    extract_aisle_paths,
    extract_next_data,
    parse_products,
    parse_store_info,
)
from rappi_co.settings import PROJECT_ROOT, DATA_RAW_DIR, DATA_CHECKPOINTS_DIR

logger = logging.getLogger(__name__)

# Render each page in the browser and let the SSR payload settle. __NEXT_DATA__ is in the initial
# HTML; a short networkidle wait also gives client-side catalogs a chance to populate.
_PLAYWRIGHT_META = {
    "playwright": True,
    "playwright_page_methods": [PageMethod("wait_for_load_state", "domcontentloaded")],
}


def _latest_stores_csv() -> Path | None:
    # the LARGEST stores file = the full enumeration. the menu spider re-emits a small
    # stores file each run, so picking "newest" would shadow the enumeration on resume
    # and silently crawl only a handful of stores.
    raw = Path(DATA_RAW_DIR)
    files = list(raw.glob("stores_*.csv"))
    return max(files, key=lambda p: p.stat().st_size) if files else None


def _slug_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    last = path.split("/")[-1]
    # last is "<id>-<slug>"; pull just the slug
    if "-" in last:
        return last.split("-", 1)[1]
    return last


class MenuSpider(scrapy.Spider):
    name = "menu"
    custom_settings = {
        "JOBDIR": str(Path(DATA_CHECKPOINTS_DIR) / "menu"),
        # Browser rendering is heavy, so keep concurrency low and pace gently; override per run with
        # -s DOWNLOAD_DELAY / -s CONCURRENT_REQUESTS_PER_DOMAIN. Autothrottle still backs off on latency.
        "CONCURRENT_REQUESTS": 2,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": 3.0,
        # close gracefully after a long idle; the jobdir lets us resume where we stopped.
        "CLOSESPIDER_TIMEOUT_NO_ITEM": 1800,
        # Pages render in the browser (see _PLAYWRIGHT_META), so the JS-shell retry is redundant.
        "DOWNLOADER_MIDDLEWARES": {"rappi_co.middlewares.JSShellRetryMiddleware": None},
    }

    def __init__(self, stores: str | None = None, max_per_store: str | int | None = None,
                 stores_csv: str | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._max_per_store = int(max_per_store) if max_per_store else None
        self._stores_filter = set(s.strip() for s in stores.split(",") if s.strip()) if stores else None
        self._counts: dict[str, int] = defaultdict(int)
        self._done = 0
        path = Path(stores_csv) if stores_csv else _latest_stores_csv()
        if path is None or not path.exists():
            raise RuntimeError(
                "No stores_*.csv found. Run `scrapy crawl stores` first or pass -a stores_csv=PATH."
            )
        self._stores_csv = path
        self._stores: list[dict] = []
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if self._stores_filter and row["store_id"] not in self._stores_filter:
                    continue
                self._stores.append(row)
        logger.info("stage 2 spider: loaded %d stores from %s", len(self._stores), path)

    async def start(self):
        # pre-emit each Store record so the dedup pipeline pre-populates its in-memory
        # dict; later landing-page parses merge in the address fields.
        for row in self._stores:
            try:
                store_types = json.loads(row.get("store_types") or "[]")
            except json.JSONDecodeError:
                store_types = [row.get("store_types") or ""]
            try:
                discovery_paths = json.loads(row.get("discovery_paths") or "[]")
            except json.JSONDecodeError:
                discovery_paths = [row.get("discovery_paths") or ""]
            yield self._make_store_item({
                "store_id": row["store_id"],
                "slug": row["slug"],
                "name": row["name"],
                "url": row["url"],
                "store_types": store_types,
                "discovery_paths": discovery_paths,
            })

        # then one browser-rendered fetch per store landing page
        for row in self._stores:
            yield scrapy.Request(
                row["url"],
                callback=self.parse_landing,
                errback=self.errback,
                meta={
                    "store_id": row["store_id"],
                    "store_slug": row["slug"],
                    "store_name": row["name"],
                    "store_url": row["url"],
                    **_PLAYWRIGHT_META,
                },
            )

    def parse_landing(self, response):
        store_id = response.meta["store_id"]
        store_slug = response.meta["store_slug"]

        payload = extract_next_data(response.text)
        if not payload:
            logger.warning("no __NEXT_DATA__ in landing %s (store %s)", response.url, store_id)
            self.crawler.stats.inc_value("menu/landing_no_next_data")
            return

        # 1) emit updated Store with address info
        info = parse_store_info(payload)
        yield {
            "_item_type": "store",
            "store_id": store_id,
            "slug": store_slug,
            "name": response.meta.get("store_name") or store_slug,
            "url": response.meta.get("store_url") or response.url,
            "store_types": [],
            "discovery_paths": [],
            **{k: v for k, v in info.items() if v is not None},
        }

        # 2) emit landing-page products
        for prod in parse_products(payload, response.url, store_id):
            if not self._under_cap(store_id):
                break
            self._counts[store_id] += 1
            yield self._make_menu_item(prod)

        # 3) queue aisle subpages
        for aisle_path in extract_aisle_paths(payload, store_id, store_slug):
            yield scrapy.Request(
                urljoin(response.url, aisle_path),
                callback=self.parse_aisle,
                errback=self.errback,
                meta={"store_id": store_id, "store_slug": store_slug, **_PLAYWRIGHT_META},
            )

        # progress: stores whose landing we've processed
        self._done += 1
        if self._done % 50 == 0:
            logger.info("processed %d/%d store landings", self._done, len(self._stores))

    def parse_aisle(self, response):
        store_id = response.meta["store_id"]
        payload = extract_next_data(response.text)
        if not payload:
            logger.warning("no __NEXT_DATA__ in aisle %s (store %s)", response.url, store_id)
            self.crawler.stats.inc_value("menu/aisle_no_next_data")
            return
        for prod in parse_products(payload, response.url, store_id):
            if not self._under_cap(store_id):
                break
            self._counts[store_id] += 1
            yield self._make_menu_item(prod)

    def _under_cap(self, store_id: str) -> bool:
        if self._max_per_store is None:
            return True
        return self._counts[store_id] < self._max_per_store

    def _make_store_item(self, row: dict) -> dict:
        return {"_item_type": "store", **row}

    def _make_menu_item(self, prod: dict) -> dict:
        return {"_item_type": "menu_item", **prod}

    def errback(self, failure):
        # scrapy-playwright manages the page lifecycle (no include_page), so just log; 403/429
        # are handled by retry/queue.
        logger.warning("request failed: %s", failure.value)
