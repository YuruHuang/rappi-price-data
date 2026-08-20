"""Parse Rappi type-index pages (e.g. /tiendas/tipo/market) into store stubs."""
from __future__ import annotations

import json
import logging
import re
from typing import Iterator, Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
_STORE_PATH_RE = re.compile(r"^/tiendas/(\d+)-([a-z0-9-]+)/?$", re.IGNORECASE)
# Rappi restaurant store landings appear in 2 URL forms (both valid, same store):
#   /restaurantes/<id>-<slug>             (legacy / direct)
#   /restaurantes/delivery/<id>-<slug>    (newer hub-link form)
_RESTAURANT_PATH_RE = re.compile(
    r"^/restaurantes(?:/delivery)?/(\d+)-([a-z0-9-]+)/?$",
    re.IGNORECASE,
)
_ANCHOR_RE = re.compile(
    r'<a[^>]+href=[\'"](?P<href>[^\'"]+)[\'"][^>]*>(?P<text>.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)


def _path_re_for(vertical: str) -> re.Pattern:
    return _RESTAURANT_PATH_RE if vertical == "restaurant" else _STORE_PATH_RE


def _url_prefix_for(vertical: str) -> str:
    return "/restaurantes/" if vertical == "restaurant" else "/tiendas/"


def parse_type_index(html: str, base_url: str, store_type: str,
                     vertical: str = "retail") -> Iterator[dict]:
    seen: set[str] = set()
    next_data = _extract_next_data(html)
    if next_data:
        # Targeted: props.pageProps.fallback[<cpgs-catalog key>].storeGroups[].stores[]
        for stub in _stores_from_catalog(next_data, base_url, store_type, vertical):
            if stub["store_id"] in seen:
                continue
            seen.add(stub["store_id"])
            yield stub
    if seen:
        return
    # Fallback A: generic dict walk (for unexpected shapes)
    if next_data:
        for stub in _walk_next_data_for_stores(next_data, base_url, store_type, vertical):
            if stub["store_id"] in seen:
                continue
            seen.add(stub["store_id"])
            yield stub
    if seen:
        return
    # Fallback B: anchor regex on raw HTML
    for stub in _anchor_scan(html, base_url, store_type, vertical):
        if stub["store_id"] in seen:
            continue
        seen.add(stub["store_id"])
        yield stub


def _stores_from_catalog(payload: dict, base_url: str, store_type: str,
                         vertical: str = "retail") -> Iterator[dict]:
    """Targeted extraction matching the observed Rappi shape:
       props.pageProps.fallback[<cpgs-catalog key>].storeGroups[].stores[]
    Each store dict has: storeId (int), name (clean), friendlyURL, image,
    etaText, vertical, subvertical, storeType.
    """
    fallback = (
        payload.get("props", {}).get("pageProps", {}).get("fallback", {})
    )
    if not isinstance(fallback, dict):
        return
    url_prefix = _url_prefix_for(vertical)
    for key, container in fallback.items():
        if not isinstance(container, dict):
            continue
        groups = container.get("storeGroups")
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            stores = group.get("stores")
            if not isinstance(stores, list):
                continue
            for s in stores:
                if not isinstance(s, dict):
                    continue
                store_id_raw = s.get("storeId") or s.get("store_id") or s.get("id")
                if store_id_raw is None:
                    continue
                store_id = str(store_id_raw).strip()
                if not store_id.isdigit():
                    continue
                name = (s.get("name") or s.get("store_name") or "").strip()
                if not name:
                    continue
                slug_raw = s.get("friendlyURL") or s.get("friendly_url") or s.get("slug")
                slug = ""
                if isinstance(slug_raw, str):
                    raw = slug_raw.strip("/").split("/")[-1]
                    # Some friendlyURLs are "<id>-<slug>", others are just "<slug>"
                    prefix = f"{store_id}-"
                    slug = raw[len(prefix):] if raw.startswith(prefix) else raw
                if not slug:
                    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or store_id
                url = urljoin(base_url, f"{url_prefix}{store_id}-{slug}")
                yield {
                    "store_id": store_id,
                    "slug": slug,
                    "name": _clean_name(name),
                    "url": url,
                    "store_type": store_type,
                    "vertical": vertical,
                }


def _extract_next_data(html: str) -> Optional[dict]:
    if not html:
        return None
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        logger.warning("__NEXT_DATA__ JSON decode failed: %s", e)
        return None


def _walk_next_data_for_stores(payload: dict, base_url: str, store_type: str,
                                vertical: str = "retail") -> Iterator[dict]:
    seen: set[str] = set()
    for d in _iter_dicts(payload):
        store_id = _coerce_id(d)
        if not store_id or store_id in seen:
            continue
        name = _coerce_name(d)
        if not name:
            continue
        slug, url = _coerce_slug_and_url(d, store_id, base_url, vertical)
        if not slug:
            continue
        # Cross-vertical guard: when crawling retail, drop /restaurantes/ URLs
        # and vice versa, so a hub's cross-promo cards don't pollute the wrong
        # vertical's output.
        if vertical == "retail" and "/restaurantes/" in url:
            continue
        if vertical == "restaurant" and "/tiendas/" in url:
            continue
        seen.add(store_id)
        yield {
            "store_id": str(store_id),
            "slug": slug,
            "name": _clean_name(str(name)),
            "url": url,
            "store_type": store_type,
            "vertical": vertical,
        }


import html as _html

_NAME_NOISE_RES = [
    # ETA range like "10 - 12 min" or "59 - 79 min" or "49 - 69 min"
    re.compile(r"\d+\s*-\s*\d+\s*min(?:utos?)?(?:\s*o\s*prog\.?)?\s*$", re.IGNORECASE),
    # Single-number ETA "30 min" / "30 min o prog." / "30 min o prog"
    re.compile(r"\d+\s*min(?:utos?)?(?:\s*o\s*prog\.?)?\s*$", re.IGNORECASE),
    # "min o prog." trailing
    re.compile(r"\bmin\s*o\s*prog\.?\s*$", re.IGNORECASE),
    # Day abbreviations like "Hoy, 11 AM" / "Sab, 10 AM" / "Mier, 12 AM"
    re.compile(r"\b(?:Hoy|Sab|Sáb|S[áa]bado|Lun|Mier|Mi[ée]r|Mi[ée]rcoles|Jue|Vie|Dom),?\s*\d+\s*[AP]M\s*$", re.IGNORECASE),
]


def _clean_name(name: str) -> str:
    """Strip Rappi UI suffixes like '30 min' / '37 min o prog.' / 'Sab, 10 AM' from store names.
    Also decode HTML entities (e.g., &amp; -> &)."""
    cleaned = _html.unescape(name)
    # Apply each pattern repeatedly until stable
    for _ in range(3):
        prev = cleaned
        for pat in _NAME_NOISE_RES:
            cleaned = pat.sub("", cleaned).rstrip()
        if cleaned == prev:
            break
    return cleaned.strip() or name.strip()


def _iter_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_dicts(v)


_STORE_ID_KEYS = ("store_id", "storeId", "id")
_STORE_NAME_KEYS = ("store_name", "name", "storeName", "title")
_STORE_SLUG_KEYS = ("slug", "friendly_url", "friendly_name", "store_slug")
_STORE_URL_KEYS = ("store_url", "url", "deeplink", "link")
_STORE_FLAGS_PRESENT = ("eta", "delivery_method", "lat", "lng", "store_type", "type",
                        "logo", "logo_url", "store_logo", "image", "background_url")


def _coerce_id(d: dict) -> Optional[str]:
    has_flag = any(k in d for k in _STORE_FLAGS_PRESENT)
    if not has_flag:
        return None
    for k in _STORE_ID_KEYS:
        v = d.get(k)
        if v is None:
            continue
        if isinstance(v, (int, str)) and str(v).strip().isdigit():
            return str(v).strip()
    return None


def _coerce_name(d: dict) -> Optional[str]:
    for k in _STORE_NAME_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


def _coerce_slug_and_url(d: dict, store_id: str, base_url: str,
                          vertical: str = "retail") -> tuple[Optional[str], str]:
    slug: Optional[str] = None
    for k in _STORE_SLUG_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            slug = v.strip().strip("/")
            break
    path_marker = "/restaurantes/" if vertical == "restaurant" else "/tiendas/"
    url_prefix = _url_prefix_for(vertical)
    path_re = _path_re_for(vertical)
    url_raw: Optional[str] = None
    for k in _STORE_URL_KEYS:
        v = d.get(k)
        if isinstance(v, str) and path_marker in v:
            url_raw = v
            break
    if url_raw:
        if url_raw.startswith("http"):
            full_url = url_raw
        else:
            full_url = urljoin(base_url, url_raw)
        if not slug:
            path = urlparse(full_url).path
            m = path_re.match(path.rstrip("/"))
            if m:
                slug = m.group(2)
    elif slug:
        full_url = urljoin(base_url, f"{url_prefix}{store_id}-{slug}")
    else:
        return None, ""
    return slug, full_url


def _anchor_scan(html: str, base_url: str, store_type: str,
                  vertical: str = "retail") -> Iterator[dict]:
    path_re = _path_re_for(vertical)
    url_prefix = _url_prefix_for(vertical)
    for m in _ANCHOR_RE.finditer(html):
        href = m.group("href")
        text = re.sub(r"<[^>]+>", "", m.group("text")).strip()
        path = urlparse(href).path if href.startswith("http") else href
        sm = path_re.match(path.rstrip("/"))
        if not sm:
            continue
        sid, slug = sm.group(1), sm.group(2)
        full_url = urljoin(base_url, f"{url_prefix}{sid}-{slug}")
        yield {
            "store_id": sid,
            "slug": slug,
            "name": text or slug.replace("-", " ").title(),
            "url": full_url,
            "store_type": store_type,
            "vertical": vertical,
        }
