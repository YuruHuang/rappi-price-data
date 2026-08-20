"""Stage 1: enumerate every storefront for the active address.

reads the store-type seeds in config/seed_paths_co.yml and fetches each under both
/tiendas/tipo/<type> and /bogota/tiendas/tipo/<type> (the two SSR responses differ).

each request is rendered with scrapy-playwright so the SPA can lazy-load all storefronts;
we extract stores from the __NEXT_DATA__ storeGroups AND from the rendered DOM anchors and
union the two. results stream to data/raw/<address>/stores_*.csv.
"""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urljoin

import scrapy
from scrapy_playwright.page import PageMethod

from rappi_co.parsers.store_index import (
    parse_type_index,
    _path_re_for,
    _url_prefix_for,
)
from rappi_co.settings import PROJECT_ROOT, ACTIVE_ZONE_SLUG, DATA_CHECKPOINTS_DIR

# per-address JOBDIR so each address's crawl is a distinct checkpoint — otherwise
# the shared seeds dedupe and the second address would scrape 0 items.
# Checkpoints live under data/co/checkpoints so each address resumes only its own
# job (a stale checkpoint would make the crawl dedupe to zero items).
_ZONE_CHECKPOINT = Path(DATA_CHECKPOINTS_DIR) / f"stores_{ACTIVE_ZONE_SLUG}_v2"

logger = logging.getLogger(__name__)


class StoresSpider(scrapy.Spider):
    name = "stores"
    custom_settings = {
        "JOBDIR": str(_ZONE_CHECKPOINT),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from rappi_co import settings as S
        from rappi_co.configs import load_seed_paths
        self._city_slug = S.CITY_SLUG
        self.base_url = S.RAPPI_BASE_URL

        # Curated retail store-type seeds from config/seed_paths_co.yml (validated load —
        # fails loud on a malformed file). Restaurants are out of scope for this dataset.
        self._seeds: list[dict] = []
        seen_paths: set[str] = set()
        for entry in load_seed_paths(PROJECT_ROOT / "config" / "seed_paths_co.yml"):
            path = entry["path"]
            if path in seen_paths:
                continue
            seen_paths.add(path)
            self._seeds.append({
                "path": path,
                "store_type": entry["store_type"],
                "vertical": "retail",
            })

        logger.info("stores spider seeds: %d retail store types", len(self._seeds))

    async def start(self):
        for entry in self._seeds:
            path = entry["path"]
            store_type = entry["store_type"]
            vertical = entry["vertical"]

            if vertical == "retail":
                tipo_slug = path.rstrip("/").split("/")[-1]
                # Two seeds per retail type: bare and /<city>-prefixed (different SSR results).
                # City slug comes from settings.CITY_SLUG (bogota).
                request_paths = (
                    f"/tiendas/tipo/{tipo_slug}",
                    f"/{self._city_slug}/tiendas/tipo/{tipo_slug}",
                )
            else:
                # Restaurant cuisines: hub UI lives at /restaurantes/category/<slug>.
                # No city prefix on the category page itself (verified from the
                # /restaurantes hub HTML on 2026-05-26).
                request_paths = (path,)

            for req_path in request_paths:
                yield scrapy.Request(
                    urljoin(self.base_url, req_path),
                    callback=self.parse_index,
                    errback=self.errback,
                    meta={
                        "store_type": store_type,
                        "vertical": vertical,
                        "discovery_path": req_path,
                        "playwright": True,
                        "playwright_include_page": True,
                        "playwright_page_methods": [
                            PageMethod("wait_for_load_state", "domcontentloaded"),
                        ],
                    },
                )

    async def parse_index(self, response):
        store_type = response.meta["store_type"]
        vertical = response.meta.get("vertical", "retail")
        discovery_path = response.meta["discovery_path"]
        page = response.meta.get("playwright_page")
        rendered_html = response.text

        if page is not None:
            try:
                # Trigger lazy-loaded cards by scrolling repeatedly to bottom
                for _ in range(20):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(500)
                rendered_html = await page.content()
            except Exception as e:
                logger.warning("scroll/render failed for %s: %s", response.url, e)
            finally:
                await page.close()

        # 1) Extract from __NEXT_DATA__ storeGroups
        ssr_count = 0
        seen: set[str] = set()
        for stub in parse_type_index(rendered_html, self.base_url, store_type, vertical=vertical):
            seen.add(stub["store_id"])
            ssr_count += 1
            yield self._make_store_item(stub, discovery_path, vertical)

        # 2) Sweep rendered DOM anchors for any extras the SSR list missed
        dom_extra = 0
        for sid, slug in self._anchors_from_html(rendered_html, vertical):
            if sid in seen:
                continue
            seen.add(sid)
            dom_extra += 1
            url_prefix = _url_prefix_for(vertical)
            yield self._make_store_item({
                "store_id": sid,
                "slug": slug,
                "name": slug.replace("-", " ").title(),  # filled later by Stage 2 landing parse
                "url": urljoin(self.base_url, f"{url_prefix}{sid}-{slug}"),
                "store_type": store_type,
                "vertical": vertical,
            }, discovery_path, vertical)

        logger.info("[%s/%s] %s -> ssr=%d, dom_extra=%d, total=%d",
                    vertical, store_type, response.url, ssr_count, dom_extra,
                    ssr_count + dom_extra)

    def _anchors_from_html(self, html: str, vertical: str):
        # scrape store id + slug from the rendered DOM anchors, to dedup against the SSR list.
        import re
        from urllib.parse import urlparse
        path_re = _path_re_for(vertical)
        seen = set()
        for m in re.finditer(r'href=["\'](?P<href>[^"\']+)["\']', html, re.IGNORECASE):
            href = m.group("href")
            path = urlparse(href).path if href.startswith("http") else href.split("?", 1)[0]
            sm = path_re.match(path.rstrip("/"))
            if not sm:
                continue
            sid = sm.group(1)
            if sid in seen:
                continue
            seen.add(sid)
            yield sid, sm.group(2)

    def _make_store_item(self, stub: dict, discovery_path: str, vertical: str) -> dict:
        return {
            "_item_type": "store",
            "store_id": stub["store_id"],
            "slug": stub["slug"],
            "name": stub["name"],
            "url": stub["url"],
            "vertical": vertical,
            "store_types": [stub["store_type"]],
            "discovery_paths": [discovery_path],
            "discovery_zones": [ACTIVE_ZONE_SLUG],
        }

    async def errback(self, failure):
        # close the playwright page a failed request leaves open, or the page pool
        # exhausts and the crawl deadlocks (same leak as the menu spider).
        page = failure.request.meta.get("playwright_page")
        if page is not None:
            try:
                await page.close()
            except Exception as e:
                # best-effort cleanup; page/context may already be gone. log, don't crash shutdown.
                logger.debug("errback page close failed (already closed?): %s", e)
        logger.warning("request failed: %s", failure.value)
