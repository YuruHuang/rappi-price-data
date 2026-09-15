"""Bounded browser pilot for Rappi's ``Información del producto`` section.

Only observed storefront URLs are navigated. Product-level canonical pages are a
separate scope; their descriptions must never be joined to store observations.
Playwright is imported only when an eligible browser request is actually needed.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parents[2]
COUNTRY_HOSTS = {code: f"www.rappi.com.{code}" for code in ("ar", "co", "pe", "mx")}
COUNTRY_API_HOSTS = {
    "ar": "services.rappi.com.ar",
    "co": "services.grability.rappi.com",
    "pe": "services.rappi.pe",
    "mx": "services.mxgrability.rappi.com",
}
PASSIVE_JSON_RESPONSE_LIMIT = 100
IDENTITY_COLUMNS = ["country_code", "zone_slug", "store_id", "product_id"]
DETAIL_COLUMNS = IDENTITY_COLUMNS + [
    "master_product_id", "name", "detail_scope", "product_information",
    "ingredients_text", "nutrition_text", "detail_status", "detail_url",
    "detail_retrieved_at", "detail_evidence_path", "detail_locale",
    "detail_identity_method", "detail_method", "detail_note",
    "ssr_product_information", "ssr_information_method",
    "detail_evidence_sha256",
]
_INFO = {"informacion del producto", "informacion de producto"}
_INGREDIENTS = {"ingredientes", "lista de ingredientes"}
_NUTRITION = {"informacion nutricional", "tabla nutricional", "datos nutricionales"}
_STOP = {"opciones adicionales de compra", "productos similares", "productos relacionados",
         "productos complementarios", "comentarios", "agregar", "ver menos", "cerrar",
         "si mi producto esta agotado", "top marcas y cadenas de restaurantes"}
_BLOCK = re.compile(
    r"captcha|access denied|acceso denegado|verify (?:that )?you are human|"
    r"verifica que eres humano|too many requests|demasiadas solicitudes|"
    r"checking your browser|verificando tu navegador|eres mayor de edad", re.I)


def _normal(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(text)).casefold().split())


def _label(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", _normal(text))
                   if unicodedata.category(c) != "Mn").rstrip(":")


def validate_url(url: str, country: str) -> str:
    """Accept HTTPS country storefronts only, never services/API or arbitrary URLs."""
    parsed = urlparse(url)
    expected = COUNTRY_HOSTS.get(country)
    if (not expected or parsed.scheme != "https" or parsed.hostname not in
            {expected, expected.removeprefix("www.")} or parsed.username or
            parsed.password or parsed.port not in (None, 443) or
            not parsed.path.startswith(("/p/", "/tiendas/")) or
            any(c in url for c in "\r\n\\")):
        raise ValueError("expected an observed HTTPS /p/ or /tiendas/ URL for this country")
    return url


def observed_url(row: dict) -> str:
    """Do not construct a route from a name, SKU, master ID, or API endpoint."""
    for field in ("browser_url", "product_url", "store_url", "source_url"):
        value = str(row.get(field) or "").strip()
        if value:
            try:
                return validate_url(value, row["country_code"])
            except (ValueError, KeyError):
                continue
    return ""


def parse_information_text(text: str) -> dict:
    """Parse a scoped visible section, retaining Spanish text and explicit units.

    No numeric inference is performed here. Full visible text is retained in the
    evidence JSON so boundaries and later extraction can be audited/replayed.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    labels = [_label(line) for line in lines]
    fields = {"product_information": "", "ingredients_text": "", "nutrition_text": ""}
    groups = [("product_information", _INFO), ("ingredients_text", _INGREDIENTS),
              ("nutrition_text", _NUTRITION)]
    for field, headings in groups:
        start = next((i + 1 for i, label in enumerate(labels) if label in headings), None)
        if start is None:
            continue
        end = len(lines)
        for i in range(start, len(lines)):
            label = labels[i]
            if (label in _STOP or label.startswith(("¿como pedir ", "¿cuanto cuesta ",
                    "productos similares en ", "productos complementarios en ", "productos relacionados en "))
                    or (field != "product_information" and
                        label in _INFO | _INGREDIENTS | _NUTRITION)):
                end = i
                break
        fields[field] = re.sub(r"\s+Ver menos\s*$", "", "\n".join(lines[start:end]), flags=re.I).strip()
    fields["information_heading_seen"] = any(label in _INFO for label in labels)
    fields["is_truncated"] = any(
        re.search(r"(?:\.{3}|…)\s*(?:Ver más)?\s*$", line, re.I)
        for field in ("product_information", "ingredients_text", "nutrition_text")
        for line in fields[field].splitlines())
    return fields


def pdp_primary(payload: dict) -> tuple[dict, dict]:
    """Read the empirically observed Next.js PDP primary product, not other stores."""
    page = payload.get("props", {}).get("pageProps", {})
    fallback = page.get("fallback", {})
    if not isinstance(fallback, dict):
        return {}, {}
    candidates = [value for key, value in fallback.items()
                  if key.startswith('@"pdp",') and isinstance(value, dict)]
    if len(candidates) != 1:
        return {}, page.get("location") or {}
    product = candidates[0].get("primaryStore", {}).get("product") or {}
    return product if isinstance(product, dict) else {}, page.get("location") or {}


def location_matches(location: dict, zone: dict | None) -> bool:
    if not zone or location.get("autoLocation") is not False:
        return False
    try:
        return (abs(float(location["lat"]) - float(zone["lat"])) <= 0.001
                and abs(float(location["lng"]) - float(zone["lng"])) <= 0.001)
    except (KeyError, TypeError, ValueError):
        return False


def parse_snapshot(snapshot: dict, row: dict, scope: str = "observation") -> dict:
    """Turn replayable browser evidence into one identity-checked detail record."""
    result = {field: "" for field in DETAIL_COLUMNS}
    result.update({field: str(row.get(field) or "")
                   for field in IDENTITY_COLUMNS + ["master_product_id", "name"]})
    result.update(detail_scope=scope, detail_url=snapshot.get("url", ""),
                  detail_locale=snapshot.get("locale", ""),
                  detail_retrieved_at=snapshot.get("retrieved_at", ""),
                  detail_method="browser_product_information")
    if scope == "product":
        result["store_id"] = ""
        result["zone_slug"] = ""

    def fail(status: str, note: str) -> dict:
        result.update(detail_status=status, detail_note=note)
        return result

    text = str(snapshot.get("text") or "")
    if snapshot.get("status") in (401, 403, 429) or snapshot.get("blocked_reason") or _BLOCK.search(text):
        return fail("blocked", snapshot.get("blocked_reason") or "access or age challenge; stop")
    if snapshot.get("status") == 404:
        return fail("not_found", "HTTP 404")
    if snapshot.get("error") or (snapshot.get("status") or 200) >= 400:
        return fail("error", str(snapshot.get("error") or f"HTTP {snapshot['status']}"))
    try:
        validate_url(result["detail_url"], row["country_code"])
    except (ValueError, KeyError):
        return fail("invalid_url", "final browser URL failed country/host/path validation")
    identity = snapshot.get("identity") or {}
    expected_name = _normal(row.get("name") or "")
    if not expected_name or _normal(identity.get("name") or "") != expected_name:
        return fail("identity_mismatch", "opened product name differs or cannot be verified")
    if not snapshot.get("product_view_verified"):
        return fail("not_found", "exact product detail view was not opened")
    if scope == "product":
        expected = str(row.get("master_product_id") or row.get("product_id") or "")
        if str(identity.get("master_product_id") or "") != expected:
            return fail("identity_mismatch", "canonical master product ID does not match")
    else:
        if any(not row.get(key) for key in IDENTITY_COLUMNS):
            return fail("identity_unverified", "observation requires all four identity keys")
        if (str(identity.get("product_id") or "") != str(row["product_id"])
                or str(identity.get("store_id") or "") != str(row["store_id"])):
            return fail("identity_mismatch", "opened product/store IDs differ or cannot be verified")
        if identity.get("method") == "pdp_primary_ids_and_heading" and not snapshot.get("primary_store_visible_matches"):
            return fail("identity_unverified", "visible primary store no longer matches the initial page payload")
        if not snapshot.get("location_verified"):
            return fail("location_unverified", "delivery zone is not explicitly verified")
    result["detail_identity_method"] = str(identity.get("method") or "")
    primary = snapshot.get("ssr_primary_product") or {}
    if (primary and _normal(primary.get("name") or "") == expected_name
            and str(primary.get("masterProductId") or "") == str(identity.get("master_product_id") or "")
            and (scope == "product" or (str(primary.get("id")) == str(row["product_id"])
                                       and str(primary.get("storeId")) == str(row["store_id"])))):
        result["ssr_product_information"] = str(primary.get("description") or "")
        result["ssr_information_method"] = "next_data_pdp_primary_product_description"
    parsed = parse_information_text(text)
    if parsed["is_truncated"]:
        return fail("truncated", "Ver más did not expose a complete description; raw text retained")
    for field in ("product_information", "ingredients_text", "nutrition_text"):
        result[field] = parsed[field]
    if any(result[field] for field in ("product_information", "ingredients_text", "nutrition_text")):
        result["detail_status"] = "ok" if scope == "observation" else "captured_product_page"
    else:
        result["detail_status"] = "no_description"
        result["detail_note"] = "verified product view has no visible product-information text"
    return result


def _timestamp(value: str) -> datetime:
    """Parse source-run or timezone-qualified browser time; never assume a local zone."""
    value = str(value)
    if re.fullmatch(r"\d{8}_\d{6}", value):
        return datetime.strptime(value, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include its timezone")
    return parsed.astimezone(timezone.utc)


def verify_observation_evidence(evidence: dict, row: dict) -> dict:
    """Re-derive observation acceptance from saved facts, not CSV status/booleans.

    This detects inconsistent or stale artifacts. Local hashes are integrity
    checks, not authentication of Rappi or protection against rewriting all files.
    """
    original, saved = evidence.get("input"), evidence.get("snapshot")
    if evidence.get("schema_version") != 1 or not isinstance(original, dict) or not isinstance(saved, dict):
        raise ValueError("detail evidence must contain an input observation and browser snapshot")
    for key in IDENTITY_COLUMNS:
        if not row.get(key) or str(original.get(key) or "") != str(row[key]):
            raise ValueError(f"detail evidence observation identity differs: {key}")
    for field in ("name", "master_product_id", "scrape_timestamp", "currency"):
        expected, actual = str(row.get(field) or ""), str(original.get(field) or "")
        if field == "name":
            expected, actual = _normal(expected), _normal(actual)
        if expected != actual or (field in {"name", "scrape_timestamp", "currency"} and not expected):
            raise ValueError(f"detail evidence source observation differs: {field}")
    try:
        retrieved, source_time = _timestamp(saved.get("retrieved_at", "")), _timestamp(row["scrape_timestamp"])
    except (ValueError, TypeError) as error:
        raise ValueError("detail evidence needs valid source and retrieval timestamps") from error
    if retrieved < source_time or retrieved > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("detail evidence retrieval predates its source observation or is in the future")
    zone = _zone(row)
    if zone is None:
        raise ValueError("detail evidence cannot verify an unknown observation location")
    for target, reference in (("latitude", "lat"), ("longitude", "lng")):
        if row.get(target) not in (None, "") and float(row[target]) != float(zone[reference]):
            raise ValueError("observation coordinates differ from its configured location")
    snapshot = dict(saved)
    if saved.get("locale") != f"es-{row['country_code'].upper()}":
        raise ValueError("detail evidence locale differs from the observation country")
    snapshot["location_verified"] = location_matches(saved.get("ssr_location") or {}, zone)
    identity = saved.get("identity") or {}
    method = identity.get("method")
    if method == "pdp_primary_ids_and_heading":
        primary = saved.get("ssr_primary_product") or {}
        if (str(primary.get("id") or "") != str(row["product_id"])
                or str(primary.get("storeId") or "") != str(row["store_id"])
                or _normal(primary.get("name") or "") != _normal(row["name"])
                or (row.get("master_product_id") and
                    str(primary.get("masterProductId") or "") != str(row["master_product_id"]))):
            raise ValueError("detail evidence primary product/store identity differs")
        snapshot["identity"] = {"name": primary["name"], "product_id": primary["id"],
                                "store_id": primary["storeId"], "master_product_id": primary.get("masterProductId"),
                                "method": method}
        links = saved.get("visible_primary_store_links") or []
        snapshot["primary_store_visible_matches"] = bool(links) and all(
            isinstance(link, str) and re.match(r"/tiendas/" + re.escape(str(row["store_id"])) + r"(?:-|/|$)", link)
            for link in links)
        snapshot["product_view_verified"] = any(
            _normal(name) == _normal(row["name"]) for name in saved.get("product_heading_names", []))
    elif method == "store_route_and_card_id_and_dialog_name":
        store = re.match(r"/tiendas/(\d+)(?:-|/|$)", urlparse(saved.get("clicked_store_url", "")).path)
        snapshot["product_view_verified"] = bool(store) and store.group(1) == str(row["store_id"]) and (
            str(saved.get("clicked_card_product_id") or "") == str(row["product_id"])) and any(
            _normal(line) == _normal(row["name"]) for line in str(saved.get("product_dialog_text") or "").splitlines())
    else:
        raise ValueError("detail evidence uses an unverified observation identity method")
    replayed = parse_snapshot(snapshot, row, "observation")
    if replayed["detail_status"] != "ok":
        raise ValueError("detail evidence failed observation replay: " + replayed["detail_status"])
    return replayed


def _zone(row: dict) -> dict | None:
    path = ROOT / "config" / "study" / f"zones_{row['country_code']}.yml"
    if not row.get("zone_slug") or not path.exists():
        return None
    import yaml
    zones = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("zones", [])
    return next((z for z in zones if z.get("slug") == row["zone_slug"]), None)


async def _scoped_information(page):
    """Find the smallest visible block containing the heading and section text."""
    boundary = await page.element_handle() if hasattr(page, "element_handle") else None
    headings = page.get_by_text(re.compile(r"^Información (?:del|de) producto$", re.I))
    for heading in await headings.all():
        if not await heading.is_visible():
            continue
        block = heading
        for _ in range(5):
            block = block.locator("..")
            if boundary is not None and not await block.evaluate("(e, root) => root.contains(e)", boundary):
                break
            text = await block.inner_text()
            if any(_label(line) not in _INFO for line in text.splitlines() if line.strip()):
                return block
    return None


async def _capture(page, row: dict, url: str, zone: dict | None, timeout: int) -> dict:
    snapshot = {"url": url, "locale": f"es-{row['country_code'].upper()}",
                "retrieved_at": datetime.now(timezone.utc).isoformat(), "text": "",
                "identity": {}, "product_view_verified": False, "location_verified": False}
    response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    snapshot["status"] = response.status if response else None
    # SSR text appears before click handlers attach. A click that produces no
    # expansion must not be called a successful description capture.
    try:
        await page.wait_for_load_state("networkidle", timeout=min(timeout, 15000))
    except Exception:
        pass
    snapshot["url"] = page.url
    validate_url(page.url, row["country_code"])
    body = await page.locator("body").inner_text()
    snapshot["text"] = body
    if snapshot["status"] in (401, 403, 404, 429) or _BLOCK.search(body):
        return snapshot
    payload = {}
    next_data = page.locator("script#__NEXT_DATA__")
    if await next_data.count() == 1:
        try:
            payload = json.loads(await next_data.inner_text())
        except ValueError:
            pass
    fallback = payload.get("props", {}).get("pageProps", {}).get("fallback", {})
    if isinstance(fallback, dict):
        snapshot["next_data_pdp_entries"] = [
            {"path": f"props.pageProps.fallback[{json.dumps(key, ensure_ascii=False)}]", "value": value}
            for key, value in fallback.items()
            if key.startswith('@"pdp",') and isinstance(value, dict)
        ]
    primary, location = pdp_primary(payload)
    snapshot["ssr_primary_product"] = primary
    snapshot["ssr_location"] = location
    information_scope = page
    if primary:
        snapshot["identity"] = {"name": primary.get("name"), "product_id": primary.get("id"),
                                "master_product_id": primary.get("masterProductId"),
                                "store_id": primary.get("storeId"), "method": "pdp_primary_ids_and_heading"}
        snapshot["location_verified"] = location_matches(location, zone)
        headings = await page.locator("h1").all_text_contents()
        snapshot["product_heading_names"] = headings
        snapshot["product_view_verified"] = any(_normal(h) == _normal(row["name"]) for h in headings)
        primary_links = await page.locator('[data-testid="primary-product-section"] a[href^="/tiendas/"]').evaluate_all(
            "elements => elements.map(e => e.getAttribute('href'))")
        snapshot["visible_primary_store_links"] = primary_links
        snapshot["primary_store_visible_matches"] = bool(primary_links) and all(
            re.match(r"/tiendas/" + re.escape(str(primary.get("storeId"))) + r"(?:-|/|$)", link)
            for link in primary_links)
    else:
        # Storefront click path: require a single exact name and an explicit ID
        # on its card. A name alone is insufficient for a store-specific join.
        store = re.match(r"/tiendas/(\d+)(?:-|/|$)", urlparse(page.url).path)
        names = page.get_by_text(row["name"], exact=True)
        if store and store.group(1) == str(row.get("store_id")) and await names.count() == 1:
            element = names.first
            card_id = await element.evaluate("""e => {
                for (let n=e, i=0; n && i<6; n=n.parentElement,i++) {
                    const id=n.getAttribute('data-product-id') || n.getAttribute('data-productid');
                    if(id) return id;
                } return ''; }""")
            if card_id == str(row["product_id"]):
                snapshot["clicked_card_product_id"] = card_id
                snapshot["clicked_store_url"] = page.url
                await element.click(timeout=timeout)
                dialog = page.locator('[role="dialog"]:visible')
                try:
                    await dialog.wait_for(timeout=timeout)
                except Exception:
                    snapshot["error"] = "exact product click did not open an identifiable dialog"
                    return snapshot
                visible_text = await dialog.inner_text()
                snapshot["product_dialog_text"] = visible_text
                if any(_normal(line) == _normal(row["name"]) for line in visible_text.splitlines()):
                    snapshot["identity"] = {"name": row["name"], "product_id": card_id,
                                            "store_id": store.group(1), "method": "store_route_and_card_id_and_dialog_name"}
                    snapshot["product_view_verified"] = True
                    snapshot["text"] = visible_text
                    information_scope = dialog
                    # A cookie written by this collector is only a request for
                    # a location. Require the independently rendered location.
                    snapshot["location_verified"] = location_matches(location, zone)
    block = await _scoped_information(information_scope)
    if block is not None:
        snapshot["text_before_expansion"] = await block.inner_text()
        for attempt in range(3):
            more = block.get_by_text(re.compile(r"^Ver más$", re.I))
            if await more.count() != 1:
                break
            if attempt:
                await page.wait_for_timeout(3000)
            if _BLOCK.search(await page.locator("body").inner_text()):
                snapshot["blocked_reason"] = "access or age challenge during expansion"
                break
            await more.click(timeout=timeout)
            await page.wait_for_timeout(1000)
            snapshot["expansion_clicked"] = True
            snapshot["expansion_attempts"] = attempt + 1
            dialogs = page.locator('[role="dialog"]:visible')
            if await dialogs.count() == 1:
                dialog_text = await dialogs.inner_text()
                if any(_label(line) in _INFO for line in dialog_text.splitlines()):
                    block = dialogs
            else:
                block = await _scoped_information(information_scope) or block
            if not parse_information_text(await block.inner_text())["is_truncated"]:
                break
        snapshot["text"] = await block.inner_text()
        snapshot["section_html"] = await block.evaluate("e => e.outerHTML")
    snapshot["url"] = page.url
    final_body = await page.locator("body").inner_text()
    if primary:
        # Hydration can change the default offer while an expansion is pending.
        # Accept the final rendered heading/store, rather than the pre-click view.
        headings = await page.locator("h1").all_text_contents()
        links = await page.locator('[data-testid="primary-product-section"] a[href^="/tiendas/"]').evaluate_all(
            "elements => elements.map(e => e.getAttribute('href'))")
        snapshot["product_heading_names"] = headings
        snapshot["visible_primary_store_links"] = links
        snapshot["product_view_verified"] = any(_normal(h) == _normal(row["name"]) for h in headings)
        snapshot["primary_store_visible_matches"] = bool(links) and all(
            re.match(r"/tiendas/" + re.escape(str(primary.get("storeId"))) + r"(?:-|/|$)", link) for link in links)
    if _BLOCK.search(final_body):
        snapshot["blocked_reason"] = "access or age challenge appeared during product interaction"
    snapshot["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    return snapshot


async def _record_passive_json_response(response, allowed_hosts: set[str], records: list[dict]) -> None:
    """Save redacted metadata for JSON already returned to a guest page.

    Endpoint paths reveal which official route the normal page used. Query
    values, response bodies, request headers, cookies and storage state are not
    retained. A path can be reviewed before a future schema-specific collector
    is allowed to preserve selected public product fields.
    """
    try:
        if urlparse(response.url).hostname not in allowed_hosts:
            return
        content_type = str((await response.all_headers()).get("content-type") or "").lower()
        if "json" not in content_type or len(records) >= PASSIVE_JSON_RESPONSE_LIMIT:
            return
        parsed = urlparse(response.url)
        item = {
            "url_without_query": parsed._replace(query="", fragment="").geturl(),
            "status": response.status,
            "method": response.request.method,
            "resource_type": response.request.resource_type,
            "content_type": content_type,
            "response_body_saved": False,
        }
        records.append(item)
    except Exception as error:
        # A failed passive read must not alter the product-page result.
        if len(records) < PASSIVE_JSON_RESPONSE_LIMIT:
            records.append({"url_without_query": "",
                            "passive_capture_error": type(error).__name__,
                            "note": "passive metadata read failed; exception text was not retained"})


async def run(input_csv: Path, out_dir: Path, *, country: str | None = None,
              limit: int = 12, scope: str = "observation", headed: bool = False,
              storage_state: Path | None = None, timeout: int = 30000,
              delay: float = 1.0) -> Path:
    if not 1 <= limit <= 500 or timeout <= 0 or delay < 0:
        raise ValueError("limit must be 1..500, timeout positive, and delay nonnegative")
    if scope not in ("observation", "product"):
        raise ValueError("scope must be observation or product")
    input_bytes = Path(input_csv).read_bytes()
    with io.StringIO(input_bytes.decode("utf-8-sig"), newline="") as source:
        rows = []
        for raw in csv.DictReader(source):
            row = {k: str(v or "").strip() for k, v in raw.items() if k}
            row["country_code"] = (row.get("country_code") or country or "").lower()
            row["zone_slug"] = row.get("zone_slug") or row.get("address_slug") or ""
            if row["country_code"] not in COUNTRY_HOSTS or not row.get("name"):
                raise ValueError("every input row requires a supported country_code and exact name")
            if country and country != row["country_code"]:
                raise ValueError("row country_code conflicts with --country")
            if scope == "observation" and any(not row.get(key) for key in IDENTITY_COLUMNS):
                raise ValueError("observation scope requires country_code, zone_slug, store_id, product_id")
            if not (row.get("master_product_id") or row.get("product_id")):
                raise ValueError("product ID is required")
            rows.append(row)
            if len(rows) == limit:
                break
    if not rows:
        raise ValueError("input CSV contains no rows")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    out_dir = Path(out_dir)
    evidence = out_dir / f"product_details_evidence_{timestamp}"
    evidence.mkdir(parents=True, exist_ok=False)
    output = out_dir / f"product_details_{timestamp}.csv"
    work = output.with_suffix(".csv.partial")
    statuses: Counter = Counter()
    evidence_hashes = {}
    blocked = False
    page_navigation_attempts = 0
    browser_requests = 0
    full_product_information = 0
    passive_json_responses = 0
    browser = manager = playwright = None
    try:
        with work.open("w", encoding="utf-8-sig", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=DETAIL_COLUMNS)
            writer.writeheader()
            for i, row in enumerate(rows):
                url = observed_url(row)
                snapshot = {"url": url, "locale": f"es-{row['country_code'].upper()}",
                            "retrieved_at": datetime.now(timezone.utc).isoformat(), "text": ""}
                direct_status = "skipped_after_block" if blocked else ("no_source_url" if not url else "")
                if not direct_status:
                    context = None
                    navigation_guard_reason = ""
                    passive_records = []
                    passive_tasks = set()
                    request_counter = {"count": 0}
                    try:
                        if browser is None:
                            from playwright.async_api import async_playwright
                            manager = async_playwright()
                            playwright = await manager.start()
                            browser = await playwright.chromium.launch(headless=not headed)
                        options = {"locale": snapshot["locale"]}
                        if storage_state:
                            options["storage_state"] = str(storage_state)
                        context = await browser.new_context(**options)
                        zone = _zone(row) if scope == "observation" else None
                        if zone:
                            loc = {"city": zone.get("city") or "", "lat": zone["lat"], "lng": zone["lng"],
                                   "address": zone.get("address", ""), "autoLocation": False, "active": True}
                            value = base64.b64encode(quote(json.dumps(loc, ensure_ascii=False)).encode()).decode()
                            await context.add_cookies([{"name": "currentLocation", "value": value,
                                                       "domain": "." + COUNTRY_HOSTS[row["country_code"]].removeprefix("www."), "path": "/"}])
                        page = await context.new_page()
                        def count_request(_request):
                            request_counter["count"] += 1
                        page.on("request", count_request)
                        def schedule_passive_capture(response):
                            site = COUNTRY_HOSTS[row["country_code"]]
                            allowed = {site, site.removeprefix("www."),
                                       COUNTRY_API_HOSTS[row["country_code"]]}
                            task = asyncio.create_task(_record_passive_json_response(
                                response, allowed, passive_records))
                            passive_tasks.add(task)
                            task.add_done_callback(passive_tasks.discard)
                        # An authorized storage state can contain personal APIs.
                        # Passive endpoint discovery is limited to fresh guest contexts.
                        if not storage_state:
                            page.on("response", schedule_passive_capture)
                        # Restrict top-level navigation, including redirects, before loading.
                        async def route_guard(route):
                            nonlocal navigation_guard_reason
                            if route.request.is_navigation_request() and route.request.frame == page.main_frame:
                                try:
                                    validate_url(route.request.url, row["country_code"])
                                except ValueError:
                                    navigation_guard_reason = "navigation left the verified country storefront path; possible login/access redirect"
                                    await route.abort()
                                    return
                            await route.continue_()
                        await page.route("**/*", route_guard)
                        page_navigation_attempts += 1
                        snapshot = await _capture(page, row, url, zone, timeout)
                    except ImportError:
                        direct_status = "browser_unavailable"
                        snapshot["error"] = "install requirements-details.txt and playwright install chromium"
                    except Exception as error:
                        snapshot["error"] = f"{type(error).__name__}: {error}"
                    finally:
                        if navigation_guard_reason:
                            snapshot["blocked_reason"] = navigation_guard_reason
                        if context:
                            await context.close()
                        if passive_tasks:
                            await asyncio.gather(*tuple(passive_tasks), return_exceptions=True)
                        snapshot["passive_json_responses"] = passive_records
                        snapshot["passive_json_response_summary"] = {
                            "enabled": not bool(storage_state),
                            "responses": len(passive_records),
                            "response_bodies_saved": False,
                            "url_queries_saved": False,
                            "request_headers_or_cookies_saved": False,
                        }
                        browser_requests += request_counter["count"]
                result = parse_snapshot(snapshot, row, scope)
                if direct_status:
                    result.update(detail_status=direct_status,
                                  detail_note=snapshot.get("error", "no browser request made"))
                key = "|".join(row.get(k, "") for k in IDENTITY_COLUMNS)
                file = evidence / f"{i + 1:04d}_{hashlib.sha256(key.encode()).hexdigest()[:12]}.json"
                result["detail_evidence_path"] = str(file.resolve())
                file.write_text(json.dumps({"schema_version": 1, "input": row,
                                            "snapshot": snapshot, "result": result},
                                           ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                evidence_hashes[file.name] = hashlib.sha256(file.read_bytes()).hexdigest()
                result["detail_evidence_sha256"] = evidence_hashes[file.name]
                writer.writerow(result)
                destination.flush()
                statuses[result["detail_status"]] += 1
                full_product_information += bool(result["product_information"])
                passive_json_responses += len(snapshot.get("passive_json_responses") or [])
                print(f"[{i+1}/{len(rows)}] {row.get('name')}: {result['detail_status']}", flush=True)
                blocked = blocked or result["detail_status"] == "blocked"
                if delay and url and not blocked:
                    await asyncio.sleep(delay)
    finally:
        if browser:
            await browser.close()
        if manager and playwright:
            await playwright.stop()
    work.replace(output)
    manifest = {"schema_version": 1, "complete": True, "scope": scope, "input": str(input_csv),
                "output": output.name, "limit": limit, "rows": len(rows),
                "run_started_utc": timestamp, "run_completed_utc": datetime.now(timezone.utc).isoformat(),
                "network_requests": browser_requests,
                "page_navigation_attempts": page_navigation_attempts,
                "full_product_information_captured": full_product_information,
                "norman_request_successes": full_product_information,
                "passive_same_origin_json_responses": passive_json_responses,
                "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
                "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "evidence_sha256": evidence_hashes,
                "status_counts": dict(statuses), "stopped_on_access_control": blocked,
                "observation_join_status": "ok only, using all four identity columns",
                "evidence_directory": evidence.name}
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="CSV with exact product names and observed browser URLs")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--country", choices=sorted(COUNTRY_HOSTS))
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--scope", choices=["observation", "product"], default="observation")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--storage-state", type=Path, help="optional existing authorized Playwright session")
    parser.add_argument("--timeout", type=int, default=30000, help="navigation/action timeout in milliseconds")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    output = asyncio.run(run(args.input, args.out, country=args.country, limit=args.limit,
                             scope=args.scope, headed=args.headed, storage_state=args.storage_state,
                             timeout=args.timeout, delay=args.delay))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
