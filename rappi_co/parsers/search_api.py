"""Client for Rappi's public unified-search endpoint.

deep per-aisle pagination is closed off (the content endpoint 204s for every aisle/sub_aisle/search
context), so depth for the relevant categories comes from unified-search instead: one POST per seed
term returns the full cross-store result set at the address, with the same product schema the SSR
parsers read plus extra signals (alcoholic_beverage, has_antismoking, ean, store_type).

The service host varies by country. ``SEARCH_URL`` remains the original Colombia default;
multicountry collection passes the host from the selected country profile.
"""
from __future__ import annotations

import logging
import time
from typing import Iterator, Optional

import httpx

from rappi_co.parsers.store_payload import _product_to_row

logger = logging.getLogger(__name__)

SEARCH_PATH = "/api/pns-global-search-api/v1/unified-search"
STUDY_SEARCH_PATH = f"{SEARCH_PATH}?is_prime=false&unlimited_shipping=false"
SEARCH_URL = f"https://services.grability.rappi.com{SEARCH_PATH}"
_HEADERS = {
    "content-type": "application/json",
    "accept": "application/json",
    "user-agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/121.0 Safari/537.36"),
    "language": "es",
}
# store-group fields we lift onto each product for provenance.
_STORE_META_KEYS = ("store_id", "store_type", "store_name", "parent_store_type",
                    "brand_name", "vertical_group")


def validate_search_payload(payload, term: str = "") -> dict:
    """Fail closed unless the response has the search endpoint's expected top-level shape."""
    label = f" for {term!r}" if term else ""
    if not isinstance(payload, dict) or not isinstance(payload.get("stores"), list):
        raise RuntimeError(
            f"search{label} returned an unexpected JSON payload; stop and check for "
            "an API error or access challenge"
        )
    return payload


def search(term: str, lat: float, lng: float, client: Optional[httpx.Client] = None,
           retries: int = 4, timeout: float = 30.0, url: str = SEARCH_URL) -> dict:
    """POST unified-search for one term at (lat,lng). retry/backoff on 429/5xx/timeout."""
    body = {"lat": float(lat), "lng": float(lng), "query": term, "options": {}}
    own = client is None
    client = client or httpx.Client(timeout=timeout, headers=_HEADERS)
    try:
        for attempt in range(1, retries + 1):
            try:
                r = client.post(url, json=body)
            except httpx.HTTPError as e:
                if attempt == retries:
                    raise RuntimeError(
                        f"search {term!r} failed after {attempt} attempts: {e}"
                    ) from e
                time.sleep(1.5 * attempt)
                continue
            if r.status_code == 200:
                try:
                    payload = r.json()
                except ValueError as e:
                    raise RuntimeError(
                        f"search {term!r} returned a non-JSON response; stop and check for "
                        "an access or browser challenge"
                    ) from e
                return validate_search_payload(payload, term)
            if r.status_code in (401, 403):
                raise RuntimeError(
                    f"search {term!r} was denied with HTTP {r.status_code}; stop and use an "
                    "authorized session or retry later"
                )
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2.0 * attempt)
                continue
            raise RuntimeError(f"search {term!r} returned HTTP {r.status_code}")
        raise RuntimeError(f"search {term!r} exhausted retries")
    finally:
        if own:
            client.close()


def iter_products(resp: dict) -> Iterator[tuple[dict, dict]]:
    """yield (store_meta, product) for every product across all store-groups."""
    validate_search_payload(resp)
    for grp in resp["stores"]:
        if not isinstance(grp, dict):
            continue
        meta = {k: grp.get(k) for k in _STORE_META_KEYS}
        for prod in (grp.get("products") or []):
            if isinstance(prod, dict):
                yield meta, prod


def search_product_to_row(store_meta: dict, prod: dict, term: str,
                          source_url: str) -> Optional[dict]:
    """map a unified-search product to the menu_items schema (via the shared _product_to_row)
    plus the search-only provenance/signal columns."""
    store_id = store_meta.get("store_id") or prod.get("store_id")
    if store_id is None:
        return None
    # category_name is the best section signal search gives us (feeds the classifier section rule).
    section = (prod.get("category_name") or "").strip()
    row = _product_to_row(prod, store_id, section, source_url)
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
        "source_term": term,
        "source": "search",
    })
    return row
