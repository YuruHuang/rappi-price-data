"""Client for Rappi's store-catalog content API (full menu items, unblocked).

Search (unified-search) is keyword-driven and caps at 25 products/store/query. The web/app loads a
store's full catalog from a different endpoint on the same grability host:

    POST services.grability.rappi.com/api/web-gateway/web/dynamic/context/content/

It needs a guest Bearer token (any browser session issues one; see fetch_guest_credentials), then it is
plain HTTP. The catalog is a component tree: store_home lists top aisles, each drilled via its
`next_context` -- sub_aisles -> aisle_detail -- with offset pagination at the leaf. This walks the
tobacco aisles (Cigarrillos, Vaporizadores, Pouches, ...) to every product, reaching stores search
surfaces but the storefront crawl cannot (marketplace + chains alike, by store_id).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Iterator, Optional

import httpx

from rappi_co.parsers.store_payload import _product_to_row

logger = logging.getLogger(__name__)

CONTENT_URL = ("https://services.grability.rappi.com"
               "/api/web-gateway/web/dynamic/context/content/")

# Top-level aisles whose name marks them as tobacco/nicotine (recall-first; the classifier decides).
TOBACCO_AISLE_RE = re.compile(
    r"cigarr|tabaco|vapor|vape|vapeo|nicotin|pouch|fumador|shisha|hookah|narguile|riesgo reducido",
    re.IGNORECASE)


def fetch_guest_credentials(storage_state_path: str, lat: float, lng: float,
                            probe_url: str = "https://www.rappi.com.co/tiendas/900139848-turbo") -> dict:
    """Open one browser session and capture the guest Bearer token + device headers the app sends."""
    import asyncio

    async def _run() -> dict:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                storage_state=storage_state_path, locale="es-CO", timezone_id="America/Bogota",
                geolocation={"latitude": float(lat), "longitude": float(lng)}, permissions=["geolocation"])
            page = await ctx.new_page()
            grabbed: dict = {}

            def on_request(req):
                if "dynamic/context/content" in req.url and req.method == "POST" and "authorization" not in grabbed:
                    grabbed.update(req.headers)

            page.on("request", on_request)
            for _ in range(2):
                if "authorization" in grabbed:
                    break
                try:
                    await page.goto(probe_url, wait_until="domcontentloaded", timeout=45000)
                    for _ in range(10):
                        if "authorization" in grabbed:
                            break
                        await page.wait_for_timeout(1500)
                except Exception as e:  # noqa: BLE001 - best effort; retry once
                    logger.warning("credential probe navigation failed: %s", e)
            await browser.close()
        keys = ("authorization", "deviceid", "app-version", "user-agent")
        creds = {k: grabbed[k] for k in keys if grabbed.get(k)}
        if "authorization" not in creds:
            raise RuntimeError("could not obtain a guest token from a browser session")
        return creds

    return asyncio.run(_run())


def _headers(creds: dict) -> dict:
    return {
        "content-type": "application/json", "accept": "application/json", "language": "es",
        "include_context_info": "true", "needappsflyerid": "false",
        "referer": "https://www.rappi.com.co/", **creds,
    }


def _post(client: httpx.Client, store_id: int, store_type: str, parent_store_type: str,
          lat: float, lng: float, context: str, state: dict, limit: int, offset: int,
          retries: int = 3) -> Optional[dict]:
    body = {"limit": limit, "offset": offset, "stores": [int(store_id)], "context": context,
            "state": {"lat": str(lat), "lng": str(lng), "store_type": store_type,
                      "parent_store_type": parent_store_type, **state}}
    for attempt in range(1, retries + 1):
        try:
            r = client.post(CONTENT_URL, json=body)
        except httpx.HTTPError as e:
            if attempt == retries:
                logger.warning("content POST failed for store %s: %s", store_id, e)
                return None
            time.sleep(1.0 * attempt)
            continue
        if r.status_code == 200:
            return r.json() if r.content else {}
        if r.status_code == 204:
            return {}
        if r.status_code in (401, 403):
            return {"_auth_error": r.status_code}
        if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(1.5 * attempt)
            continue
        return None


def _components(resp: Optional[dict]) -> list:
    return ((resp or {}).get("data") or {}).get("components") or []


def _walk_products(resp: Optional[dict]) -> Iterator[dict]:
    stack = [resp]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("product_id") or node.get("id"):
                if node.get("name") is not None and node.get("price") is not None:
                    yield node
                    continue
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


class AuthExpired(Exception):
    """The guest token was rejected (401/403); refresh credentials and retry."""


def iter_store_tobacco_products(client: httpx.Client, store_id, store_type: str,
                                parent_store_type: str, lat: float, lng: float) -> dict:
    """Return {product_id: product} for every product in a store's tobacco aisles."""
    out: dict = {}

    def check(resp):
        if isinstance(resp, dict) and resp.get("_auth_error"):
            raise AuthExpired(str(resp["_auth_error"]))
        return resp

    def descend(component, depth=0):
        if depth > 4:
            return
        nc = component.get("next_context")
        ctx = nc if isinstance(nc, str) else (nc or {}).get("context")
        state = component.get("state") or {}
        # Leaf: paginate all products. Stop only on a genuinely short/empty page from a *successful*
        # POST -- a failed POST (resp None) must NOT be read as "empty page" or it silently truncates
        # the aisle. product_count is a hint (often 0 for age-gated aisles), so never cap pagination on
        # it; a hard offset ceiling backstops a misbehaving endpoint.
        if ctx == "aisle_detail":
            offset = 0
            while offset < 5000:
                resp = check(_post(client, store_id, store_type, parent_store_type, lat, lng,
                                   "aisle_detail", state, 100, offset))
                if resp is None:  # POST failed after retries; stop rather than assume empty
                    break
                got = list(_walk_products(resp))
                for p in got:
                    out[str(p.get("product_id") or p.get("id"))] = p
                if len(got) < 100:
                    break
                offset += 100
            return
        # Branch: fetch children and recurse (preview products picked up too).
        if ctx in ("sub_aisles", "aisle"):
            resp = check(_post(client, store_id, store_type, parent_store_type, lat, lng,
                               ctx, state, 100, 0))
            for p in _walk_products(resp):
                out[str(p.get("product_id") or p.get("id"))] = p
            for child in _components(resp):
                descend(child, depth + 1)
            return
        # No further context: keep any preview products on the component.
        for p in ((component.get("resource") or {}).get("products") or []):
            out[str(p.get("product_id") or p.get("id"))] = p

    # Enumerate all top-level aisles by paging store_home; descend the tobacco ones.
    aisles: dict = {}
    offset = 0
    while offset < 400:
        resp = check(_post(client, store_id, store_type, parent_store_type, lat, lng,
                           "store_home", {}, 20, offset))
        new = 0
        for comp in _components(resp):
            res = comp.get("resource") or {}
            aid = res.get("id")
            if aid and aid not in aisles:
                aisles[aid] = comp
                new += 1
        if new == 0:
            break
        offset += 20
    for comp in aisles.values():
        name = (comp.get("resource") or {}).get("name") or ""
        if TOBACCO_AISLE_RE.search(name):
            descend(comp)
    return out


def catalog_product_to_row(prod: dict, store_meta: dict, source_url: str) -> Optional[dict]:
    """Map a catalog product to the menu_items row schema (same shape as search rows)."""
    store_id = store_meta.get("store_id") or prod.get("store_id")
    if store_id is None:
        return None
    section = (prod.get("category_name") or "").strip()
    row = _product_to_row(prod, str(store_id), section, source_url)
    if not row:
        return None
    row.update({
        "store_type": store_meta.get("store_type") or prod.get("store_type"),
        "store_name": store_meta.get("store_name") or prod.get("store_name") or None,
        "parent_store_type": store_meta.get("parent_store_type"),
        "ean": (str(prod["ean"]).strip() or None) if prod.get("ean") not in (None, "") else None,
        "alcoholic_beverage": prod.get("alcoholic_beverage"),
        "restriction_tag": (prod.get("restriction_tag") or None),
        "requires_medical_prescription": prod.get("requires_medical_prescription"),
        "source_term": "catalog",
        "source": "catalog",
    })
    return row
