"""Downloader middlewares: UA rotation, session cookies, JS-shell retry."""
from __future__ import annotations

import json
import logging
import random
from pathlib import Path

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]


class UserAgentRotator:
    def process_request(self, request, spider):
        request.headers.setdefault("User-Agent", random.choice(_USER_AGENTS))
        request.headers.setdefault("Accept-Language", "es-CO,es;q=0.9,en;q=0.7")


class SessionCookiesMiddleware:
    """inject the saved session cookies for the active address.

    settings.STORAGE_STATE_PATH points at data/state/<address>.json (written by
    bootstrap.py); this merges those cookies into every plain (non-browser) request so
    they share the same session that's pinned to this delivery address.
    """

    def __init__(self):
        self._cookies: list[dict] = []
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        from rappi_co import settings as S
        path = Path(S.STORAGE_STATE_PATH)
        if path.exists():
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                self._cookies = state.get("cookies") or []
                logger.info("Loaded %d cookies for zone=%s from %s",
                            len(self._cookies), S.ACTIVE_ZONE_SLUG, path)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Could not load %s: %s", path, e)
        else:
            logger.warning("No %s — proceeding without geo cookies (zone=%s)",
                           path, S.ACTIVE_ZONE_SLUG)
        self._loaded = True

    def process_request(self, request, spider):
        self._load()
        if not self._cookies:
            return None
        merged = dict(request.cookies or {})
        for c in self._cookies:
            name = c.get("name")
            value = c.get("value")
            if name and value is not None and name not in merged:
                merged[name] = value
        request.cookies = merged
        return None


class JSShellRetryMiddleware:
    JS_SHELL_MARKER = b'__NEXT_DATA__'

    def process_response(self, request, response, spider):
        if request.meta.get("playwright"):
            return response
        if request.meta.get("_js_retry_done"):
            return response
        if response.status != 200:
            return response
        body = response.body or b""
        if self.JS_SHELL_MARKER in body:
            return response
        ctype = response.headers.get("Content-Type", b"").decode("latin-1", errors="ignore")
        if "html" not in ctype.lower():
            return response
        new_request = request.replace(dont_filter=True)
        new_request.meta["playwright"] = True
        new_request.meta["_js_retry_done"] = True
        logger.info("JS-shell retry via Playwright: %s", request.url)
        return new_request
