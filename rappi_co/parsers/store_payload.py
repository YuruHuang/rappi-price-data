"""Parse Rappi store landing / aisle pages by reading __NEXT_DATA__."""
from __future__ import annotations

import json
import logging
import re
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


def extract_next_data(html: str) -> Optional[dict]:
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


def _storefront_objects(payload: dict) -> Iterator[dict]:
    """Retail storefronts only: keys like `storefront/<id>`."""
    fallback = (payload.get("props", {}).get("pageProps", {}).get("fallback", {}))
    if not isinstance(fallback, dict):
        return
    for k, v in fallback.items():
        if isinstance(v, dict) and k.startswith("storefront/"):
            yield v


def _restaurant_objects(payload: dict) -> Iterator[dict]:
    """Restaurant fallback values: keys like `@"restaurant/<id>",...` (quoted, JSON
    serialized key the Next.js client uses). The value carries corridors[] etc."""
    fallback = (payload.get("props", {}).get("pageProps", {}).get("fallback", {}))
    if not isinstance(fallback, dict):
        return
    for k, v in fallback.items():
        if not isinstance(v, dict):
            continue
        # Match either bare `restaurant/<id>` or the JSON-quoted `@"restaurant/<id>",...`
        # form Rappi's Next.js uses on landing pages.
        if k.startswith("restaurant/") or "restaurant/" in k:
            # Heuristic: avoid catching `related_restaurants` etc. — must have a
            # `corridors` field OR a `storeType=="restaurant"` field.
            if "corridors" in v or v.get("storeType") == "restaurant" or v.get("partnerType") == "restaurant":
                yield v


def _components(payload: dict, key: str) -> Iterator[dict]:
    for sf in _storefront_objects(payload):
        resp = sf.get(key) or {}
        data = (resp.get("data") or {})
        for c in (data.get("components") or []):
            if isinstance(c, dict):
                yield c


def parse_products(payload: dict, source_url: str, store_id: str) -> Iterator[dict]:
    if not payload:
        return
    seen: set[tuple[str, str]] = set()

    # --- Retail path: components nested under store_home_response / sub_aisles_response ---
    for slot in ("store_home_response", "sub_aisles_response"):
        for comp in _components(payload, slot):
            resource = comp.get("resource") or {}
            section = resource.get("name") or ""
            for prod in (resource.get("products") or []):
                row = _product_to_row(prod, store_id, section, source_url)
                if not row:
                    continue
                key = (row["store_id"], row["product_id"])
                if key in seen:
                    continue
                seen.add(key)
                yield row

    # --- Restaurant path: corridors[].products[] at fallback top-level ---
    for ro in _restaurant_objects(payload):
        for corridor in (ro.get("corridors") or []):
            if not isinstance(corridor, dict):
                continue
            section = corridor.get("name") or corridor.get("title") or ""
            corridor_id = corridor.get("id")
            for prod in (corridor.get("products") or corridor.get("items") or []):
                if not isinstance(prod, dict):
                    continue
                row = _restaurant_product_to_row(prod, store_id, section, corridor_id, source_url)
                if not row:
                    continue
                key = (row["store_id"], row["product_id"])
                if key in seen:
                    continue
                seen.add(key)
                yield row


def extract_aisle_paths(payload: dict, store_id: str, store_slug: str) -> list[str]:
    if not payload:
        return []
    # Restaurants embed every corridor's products in the landing payload —
    # no aisle sub-pages to crawl. Skip aisle queueing for them.
    if any(_restaurant_objects(payload)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for sf in _storefront_objects(payload):
        atr = sf.get("aisles_tree_response") or {}
        for c in ((atr.get("data") or {}).get("components") or []):
            if not isinstance(c, dict):
                continue
            res = c.get("resource") or {}
            slug = res.get("friendly_url") or res.get("slug")
            if isinstance(slug, str) and slug and slug not in seen:
                seen.add(slug)
                out.append(f"/tiendas/{store_id}-{store_slug}/{slug.strip('/')}")
            for child in (res.get("sub_aisles") or []):
                if isinstance(child, dict):
                    cslug = child.get("friendly_url") or child.get("slug")
                    if isinstance(cslug, str) and cslug and cslug not in seen:
                        seen.add(cslug)
                        out.append(f"/tiendas/{store_id}-{store_slug}/{cslug.strip('/')}")
    return out


_ADDRESS_PATHS = ("store", "store_info", "address", "location", "coordinates", "geo",
                  "store_address", "header", "info")
_ADDRESS_TEXT_KEYS = ("address", "formatted_address", "addressLine1", "address_line_1",
                      "street", "store_address", "full_address")
_LAT_KEYS = ("lat", "latitude")
_LNG_KEYS = ("lng", "lon", "longitude")
_NEIGHBORHOOD_KEYS = ("neighborhood", "hood", "barrio")
_DISTRICT_KEYS = ("district", "distrito")
_LOCALITY_KEYS = ("locality", "city", "ciudad")
_POSTAL_KEYS = ("postal_code", "zipcode", "zip", "postcode")


def parse_store_info(payload: dict) -> dict:
    out = {
        "address_text": None, "lat": None, "lng": None,
        "neighborhood": None, "district": None, "locality": None,
        "postal_code": None, "raw_store_info": None,
    }
    if not payload:
        return out
    candidates: list[dict] = []
    for sf in _storefront_objects(payload):
        shr = sf.get("store_home_response") or {}
        data = (shr.get("data") or {})
        for path_key in _ADDRESS_PATHS:
            sub = data.get(path_key)
            if isinstance(sub, dict):
                candidates.append(sub)
        for d in _iter_dicts(data):
            if _looks_address_like(d):
                candidates.append(d)
    # Restaurant landing pages put address, lat/lng, city, district at the top
    # level of the fallback value (alongside corridors[]).
    for ro in _restaurant_objects(payload):
        candidates.append(ro)
        for d in _iter_dicts(ro):
            if _looks_address_like(d):
                candidates.append(d)
    if not candidates:
        return out
    raw_union: dict = {}
    for c in candidates:
        if not out["address_text"]:
            out["address_text"] = _first_str(c, _ADDRESS_TEXT_KEYS)
        if out["lat"] is None:
            out["lat"] = _first_float(c, _LAT_KEYS)
        if out["lng"] is None:
            out["lng"] = _first_float(c, _LNG_KEYS)
        if not out["neighborhood"]:
            out["neighborhood"] = _first_str(c, _NEIGHBORHOOD_KEYS)
        if not out["district"]:
            out["district"] = _first_str(c, _DISTRICT_KEYS)
        if not out["locality"]:
            out["locality"] = _first_str(c, _LOCALITY_KEYS)
        if not out["postal_code"]:
            out["postal_code"] = _first_str(c, _POSTAL_KEYS)
        for k, v in c.items():
            if isinstance(v, (str, int, float, bool)) and k not in raw_union:
                raw_union[k] = v
    if raw_union:
        try:
            out["raw_store_info"] = json.dumps(raw_union, ensure_ascii=False)
        except (TypeError, ValueError):
            out["raw_store_info"] = None
    if out["lat"] is not None and not (-90 <= out["lat"] <= 90):
        out["lat"] = None
    if out["lng"] is not None and not (-180 <= out["lng"] <= 180):
        out["lng"] = None
    return out


def _looks_address_like(d: dict) -> bool:
    keys = set(d.keys())
    address_signals = set(_ADDRESS_TEXT_KEYS) | set(_LAT_KEYS) | set(_LNG_KEYS) \
        | set(_DISTRICT_KEYS) | set(_NEIGHBORHOOD_KEYS) | set(_POSTAL_KEYS)
    return bool(keys & address_signals)


def _first_str(d: dict, keys) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _first_float(d: dict, keys) -> Optional[float]:
    for k in keys:
        v = d.get(k)
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _iter_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_dicts(v)


# Product images arrive as bare filenames; the CDN serves them under this base.
_IMAGE_BASE = "https://images.rappi.com.co/products/"
# Count units (cigarettes: quantity=10/20, unit_type="und") — pack size, not a volume.
_COUNT_UNITS = {"und", "unidad", "unidades", "u", "pieza", "piezas"}

# Some Rappi product names carry invisible zero-width / BOM characters (U+200B-200D, U+FEFF) that
# break exact-string joins and dedup downstream. Strip them at the source so names stay clean.
_ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\ufeff]")


def clean_name(name) -> str:
    """Trim a product name and drop invisible zero-width/BOM characters."""
    return _ZERO_WIDTH_RE.sub("", str(name or "")).strip()


def _full_image_url(image) -> Optional[str]:
    if not image or not isinstance(image, str):
        return None
    return image if image.startswith("http") else _IMAGE_BASE + image.lstrip("/")


def _product_to_row(prod: dict, store_id: str, section: str, source_url: str) -> Optional[dict]:
    pid = prod.get("product_id") or prod.get("id")
    if not pid:
        return None
    pid = str(pid).split("_")[-1]
    name = clean_name(prod.get("name"))
    if not name:
        return None
    master_pid = prod.get("master_product_id")
    price = _to_float(prod.get("price"))
    original = _to_float(prod.get("real_price"))
    discount = _to_float(prod.get("discount"))
    if discount is None and price is not None and original and original > price:
        discount = round(1 - price / original, 4)
    presentation = prod.get("presentation") or ""
    quantity_val = _to_float(prod.get("quantity"))
    unit_type = (prod.get("unit_type") or "").lower()
    pack_count, volume_ml = _derive_volume(presentation, quantity_val, unit_type)
    # Count-based products carry the pack size in `quantity` ONLY when it is a genuine
    # multi-unit count (e.g. quantity=10 for a 10-stick pack). quantity=1 just means "one
    # unit/pack" and says nothing about sticks-per-pack, so leave pack_count unknown then
    # (the name parser fills it if the name states "20 Und"); a wrong 1 would corrupt
    # price-per-stick.
    if pack_count is None and quantity_val and quantity_val > 1 and unit_type in _COUNT_UNITS:
        if float(quantity_val).is_integer() and quantity_val <= 100:
            pack_count = int(quantity_val)
    available = bool(prod.get("is_available", True))
    in_stock = bool(prod.get("in_stock", True))
    out_of_stock = prod.get("possibly_out_of_stock") or not (available or in_stock)
    pum = prod.get("pum") or ""
    unit_price, unit_price_unit = _parse_pum(pum)
    attributes = prod.get("attributes") if isinstance(prod.get("attributes"), dict) else {}
    return {
        "product_id": pid,
        "master_product_id": str(master_pid) if master_pid is not None else None,
        "store_id": str(store_id),
        "name": name,
        "brand": (prod.get("trademark") or prod.get("store_brand_name") or "").strip() or None,
        "price_cop": price,
        "original_price_cop": original,
        "discount_pct": discount,
        "unit_price_cop": unit_price,
        "unit_price_unit": unit_price_unit,
        "volume_ml": volume_ml,
        "pack_count": pack_count,
        "pack_format_raw": presentation or None,
        "menu_section": section or None,
        "menu_subsection": prod.get("category_name") or None,
        "category_id": (str(prod.get("category_id")) if prod.get("category_id") is not None else None),
        "thumbnail_url": _full_image_url(prod.get("image_url") or prod.get("image")),
        "short_description": (prod.get("description") or "").strip()[:1000] or None,
        "availability": "out_of_stock" if out_of_stock else "in_stock",
        "age_restriction": prod.get("age_restriction"),
        "has_antismoking": prod.get("has_antismoking"),
        # Extra signals lifted from the unified-search JSON.
        "stock": _to_int(prod.get("stock")),
        "quantity": quantity_val,
        "min_purchasing_units": _to_int(prod.get("min_purchasing_units")),
        "sale_type": prod.get("sale_type") or None,
        "is_medical_product": prod.get("is_medical_product"),
        "identification_required": prod.get("identification_required"),
        "store_brand_name": (prod.get("store_brand_name") or "").strip() or None,
        "retail_id": prod.get("retail_id") or None,
        "supplier": (str(attributes.get("supplier") or "").strip() or None) if attributes else None,
        "has_menthol": attributes.get("has_menthol") if attributes else None,
        "attributes_json": json.dumps(attributes, ensure_ascii=False) if attributes else None,
        "source_url": source_url,
    }


def _restaurant_product_to_row(prod: dict, store_id: str, section: str,
                                corridor_id, source_url: str) -> Optional[dict]:
    """Map a restaurant `corridors[].products[]` entry to MenuItem schema.

    Restaurant products have a much flatter shape than retail: id, name,
    description, price, realPrice, image (a filename), corridorId, isAvailable.
    No volume/pack, no brand, no PUM, no master_product_id.
    """
    pid = prod.get("id") or prod.get("product_id")
    if not pid:
        return None
    pid = str(pid)
    name = clean_name(prod.get("name"))
    if not name:
        return None
    # On restaurant menus `realPrice` is the original price (struck out when on
    # promo) and `price` is what the customer pays. Mirror retail semantics:
    # price_cop = current price, original_price_cop = pre-discount.
    current = _to_float(prod.get("price"))
    real = _to_float(prod.get("realPrice") or prod.get("real_price"))
    if current is None and real is not None:
        current = real
    if real is None or (current is not None and real <= current):
        original = current
    else:
        original = real
    discount = _to_float(prod.get("discountInPercent"))
    if discount is not None:
        # Field is in percent (0-100); normalize to fraction (0-1) to match retail.
        discount = discount / 100.0 if discount > 1 else discount
    elif (original is not None and current is not None and original > current and original > 0):
        discount = round(1 - current / original, 4)
    image = prod.get("image")
    if isinstance(image, str) and image and not image.startswith("http"):
        image = _IMAGE_BASE + image.lstrip("/")
    is_available = prod.get("isAvailable")
    return {
        "product_id": pid,
        "master_product_id": None,
        "store_id": str(store_id),
        "name": name,
        "brand": None,
        "price_cop": current,
        "original_price_cop": original,
        "discount_pct": discount,
        "unit_price_cop": None,
        "unit_price_unit": None,
        "volume_ml": None,
        "pack_count": None,
        "pack_format_raw": None,
        "menu_section": section or None,
        "menu_subsection": None,
        "category_id": (str(corridor_id) if corridor_id is not None else None),
        "thumbnail_url": image,
        "short_description": (prod.get("description") or "").strip()[:1000] or None,
        "availability": "in_stock" if is_available else "out_of_stock",
        "age_restriction": None,
        "has_antismoking": None,
        "source_url": source_url,
    }


_PRESENTATION_RE = re.compile(
    r"(?P<count>\d+(?:[.,]\d+)?)\s*[xX×]\s*(?P<vol>\d+(?:[.,]\d+)?)\s*(?P<unit>m[lL]|[lL]|[gG]|k[gG]|cc|oz)"
)
_VOL_ONLY_RE = re.compile(r"(?P<vol>\d+(?:[.,]\d+)?)\s*(?P<unit>m[lL]|[lL]|cc|oz)")


def _derive_volume(presentation: str, quantity_val, unit_type: str):
    if presentation:
        m = _PRESENTATION_RE.search(presentation)
        if m:
            count = int(float(m.group("count").replace(",", ".")))
            vol = float(m.group("vol").replace(",", "."))
            ml = _to_ml(vol, m.group("unit").lower())
            return count, ml
        m = _VOL_ONLY_RE.search(presentation)
        if m:
            vol = float(m.group("vol").replace(",", "."))
            ml = _to_ml(vol, m.group("unit").lower())
            return 1, ml
    if quantity_val is not None and unit_type:
        ml = _to_ml(quantity_val, unit_type)
        if ml is not None:
            return 1, ml
    return None, None


def _to_ml(vol: float, unit: str) -> Optional[float]:
    unit = unit.lower()
    if unit in ("ml", "cc"):
        return vol
    if unit == "l":
        return vol * 1000
    if unit == "oz":
        return vol * 29.5735
    return None


# Price-per-unit ("PUM"), e.g. "$12.500/kg" or "730/und" (the "$" prefix is often absent).
_PUM_RE = re.compile(r"(?:\$\s*)?([\d.,]+)\s*/\s*([a-zA-Z]+)")


def _parse_amount(raw: str) -> float | None:
    """Parse a numeric amount from a Colombian price string.

    COP: '12.500' (thousands '.', no decimals — Colombian convention).
    """
    s = (raw or "").strip()
    if not s:
        return None
    # COP is almost always an integer; the '.' is a thousands separator.
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_pum(pum: str):
    if not pum:
        return None, None
    m = _PUM_RE.search(pum)
    if not m:
        return None, None
    return _parse_amount(m.group(1)), m.group(2).lower()


def _to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v):
    f = _to_float(v)
    return int(f) if f is not None else None
