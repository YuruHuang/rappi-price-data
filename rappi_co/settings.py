"""Scrapy settings for the Rappi Colombia scraper (one country, one city: Bogotá).

the active delivery address is chosen with RAPPI_ADDRESS (a slug from config/zones_co.yml).
it drives the browser geolocation and the saved session cookies (data/state/<slug>.json),
and isolates outputs under data/{raw,checkpoints}/<slug>/ so the two addresses don't mix.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).absolute().parents[1]   # repo root (rappi-colombia/)

# Fixed target: Colombia, Bogotá. The spiders read CITY_SLUG and RAPPI_BASE_URL.
CITY_SLUG = "bogota"
RAPPI_BASE_URL = os.environ.get("RAPPI_BASE_URL", "https://www.rappi.com.co")
ACCEPT_LANGUAGE = "es-CO,es;q=0.9,en;q=0.7"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/121.0 Safari/537.36")


def _active_address() -> dict:
    # RAPPI_ADDRESS picks a zone slug from config/zones_co.yml; default = first zone.
    # load_zones() validates the file and fails loud on a malformed config.
    from rappi_co.configs import load_zones
    zones = load_zones(PROJECT_ROOT / "config" / "zones_co.yml")
    slug = os.environ.get("RAPPI_ADDRESS", zones[0]["slug"])
    for z in zones:
        if z["slug"] == slug:
            return z
    raise ValueError(
        f"RAPPI_ADDRESS={slug!r} is not configured; expected one of "
        f"{[z['slug'] for z in zones]}"
    )


_ADDR = _active_address()
ACTIVE_ZONE_SLUG = _ADDR["slug"]
ACTIVE_ZONE_LAT = float(_ADDR["lat"])
ACTIVE_ZONE_LNG = float(_ADDR["lng"])
STORAGE_STATE_PATH = str(PROJECT_ROOT / "data" / "state" / f"{ACTIVE_ZONE_SLUG}.json")

# --- scrapy core ----------------------------------------------------------
BOT_NAME = "rappi_co"
SPIDER_MODULES = ["rappi_co.spiders"]
NEWSPIDER_MODULE = "rappi_co.spiders"

ROBOTSTXT_OBEY = True
# Pacing knobs are env-overridable so a gentle off-peak run can slow right down without editing code:
#   RAPPI_DOWNLOAD_DELAY=3 RAPPI_CONCURRENCY=1 RAPPI_TARGET_CONCURRENCY=1.0 scrapy crawl ...
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = int(os.environ.get("RAPPI_CONCURRENCY", "2"))
DOWNLOAD_DELAY = float(os.environ.get("RAPPI_DOWNLOAD_DELAY", "0.5"))
DOWNLOAD_TIMEOUT = 30

# self-throttle so we stay under rappi's rate limits on long crawls.
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 30.0
AUTOTHROTTLE_TARGET_CONCURRENCY = float(os.environ.get("RAPPI_TARGET_CONCURRENCY", "1.5"))

RETRY_ENABLED = True
RETRY_TIMES = 4
RETRY_HTTP_CODES = [429, 500, 502, 503, 504, 522, 524, 408]
HTTPCACHE_ENABLED = False

DOWNLOADER_MIDDLEWARES = {
    "scrapy.downloadermiddlewares.useragent.UserAgentMiddleware": None,
    "rappi_co.middlewares.UserAgentRotator": 400,
    "rappi_co.middlewares.SessionCookiesMiddleware": 500,   # injects the saved session cookies
    "rappi_co.middlewares.JSShellRetryMiddleware": 600,
}
ITEM_PIPELINES = {
    "rappi_co.pipelines.ValidationPipeline": 100,
    "rappi_co.pipelines.CrossTypeDedupPipeline": 200,
    "rappi_co.pipelines.CsvWriterPipeline": 300,
}

# scrapy-playwright as the js-render fallback.
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {"headless": True}
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 60_000
# hang fix: cap open pages so a leaked page fails fast instead of deadlocking the crawl.
PLAYWRIGHT_MAX_PAGES_PER_CONTEXT = 6

_state = STORAGE_STATE_PATH if Path(STORAGE_STATE_PATH).exists() else None
PLAYWRIGHT_CONTEXTS = {
    "default": {
        "locale": "es-CO",
        "timezone_id": "America/Bogota",
        "geolocation": {"latitude": ACTIVE_ZONE_LAT, "longitude": ACTIVE_ZONE_LNG},
        "permissions": ["geolocation"],
        "storage_state": _state,
        "user_agent": USER_AGENT,
    }
}

# outputs isolated per address.
DATA_RAW_DIR = str(PROJECT_ROOT / "data" / "raw" / ACTIVE_ZONE_SLUG)
DATA_REPORTS_DIR = str(PROJECT_ROOT / "data" / "reports" / ACTIVE_ZONE_SLUG)
DATA_CHECKPOINTS_DIR = str(PROJECT_ROOT / "data" / "checkpoints" / ACTIVE_ZONE_SLUG)

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
FEED_EXPORT_ENCODING = "utf-8-sig"

for _d in (DATA_RAW_DIR, DATA_REPORTS_DIR, DATA_CHECKPOINTS_DIR,
           str(PROJECT_ROOT / "data" / "state")):
    Path(_d).mkdir(parents=True, exist_ok=True)
