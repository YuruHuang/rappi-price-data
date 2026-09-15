"""Replay checks for provenance, identity, visible Spanish sections and failures."""
import asyncio
import csv
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from rappi_co.collect.product_details import (
    _record_passive_json_response,
    location_matches, observed_url, parse_information_text, parse_snapshot,
    pdp_primary, run, validate_url,
)


def row(**overrides):
    return {"country_code": "co", "zone_slug": "centro", "store_id": "15",
            "product_id": "123", "master_product_id": "456", "name": "Agua Prueba 500 ml",
            **overrides}


def snapshot(**overrides):
    return {"url": "https://www.rappi.com.co/p/agua-prueba-456", "status": 200,
            "locale": "es-CO", "retrieved_at": "2026-09-09T12:00:00+00:00",
            "text": "Información del producto\nAgua mineral. Contenido 500 ml.\nVer menos",
            "identity": {"name": "Agua Prueba 500 ml", "product_id": "123",
                         "master_product_id": "456", "store_id": "15", "method": "verified_fixture"},
            "product_view_verified": True, "location_verified": True, **overrides}


@pytest.mark.parametrize("url", [
    "http://www.rappi.com.co/p/agua-1", "https://www.rappi.com.co.evil.example/p/agua-1",
    "https://www.rappi.com.co@evil.example/p/agua-1", "https://evil.example/p/agua-1",
    "https://www.rappi.com.ar/p/agua-1", "https://services.grability.rappi.com/api/search",
    "https://www.rappi.com.co:9443/p/agua-1", "file:///tmp/product.html",
    "https://www.rappi.com.co/api/search", "https://name@www.rappi.com.co/p/agua-1",
])
def test_rejects_unverified_country_and_host(url):
    with pytest.raises(ValueError):
        validate_url(url, "co")


def test_url_selection_never_invents_product_route():
    assert observed_url(row(source_url="unified-search?query=agua")) == ""
    url = "https://www.rappi.com.co/tiendas/15-supermercado"
    assert observed_url(row(store_url=url)) == url


def test_preserves_exact_description_and_stops_before_recommendations():
    text = "Información del producto\n1 cajetilla de 10 cigarrillos.\nSabor de prueba.\nOpciones adicionales de compra\nOTRO PRODUCTO"
    parsed = parse_information_text(text)
    assert parsed["product_information"] == "1 cajetilla de 10 cigarrillos.\nSabor de prueba."
    assert parsed["information_heading_seen"] and not parsed["is_truncated"]


def test_spanish_ingredients_nutrition_and_basis_are_retained_without_inference():
    text = "INFORMACIÓN DEL PRODUCTO:\nBebida de prueba 330 ml.\nIngredientes:\nAgua, azúcar.\nInformación nutricional\nPorción 200 ml\nAzúcares 21,2 g\nCerrar"
    parsed = parse_information_text(text)
    assert parsed["ingredients_text"] == "Agua, azúcar."
    assert parsed["nutrition_text"] == "Porción 200 ml\nAzúcares 21,2 g"
    assert "21,2 g" in parsed["product_information"]


def test_captured_requires_all_observation_keys():
    result = parse_snapshot(snapshot(), row())
    assert result["detail_status"] == "ok"
    assert result["store_id"] == "15" and result["zone_slug"] == "centro"
    assert result["product_information"] == "Agua mineral. Contenido 500 ml."
    assert parse_snapshot(snapshot(), row(zone_slug=""))["detail_status"] == "identity_unverified"


@pytest.mark.parametrize("changed", [{"store_id": "16"}, {"product_id": "124"},
                                      {"name": "Agua Prueba 1500 ml"}])
def test_wrong_product_or_store_never_copies_text(changed):
    evidence = snapshot()
    evidence["identity"].update(changed)
    result = parse_snapshot(evidence, row())
    assert result["detail_status"] == "identity_mismatch"
    assert result["product_information"] == ""


def test_stale_primary_store_does_not_become_observation_data():
    evidence = snapshot(primary_store_visible_matches=False)
    evidence["identity"]["method"] = "pdp_primary_ids_and_heading"
    assert parse_snapshot(evidence, row())["detail_status"] == "identity_unverified"


def test_canonical_evidence_is_separate_from_store_and_zone():
    result = parse_snapshot(snapshot(location_verified=False), row(), "product")
    assert result["detail_status"] == "captured_product_page"
    assert result["store_id"] == result["zone_slug"] == ""
    assert parse_snapshot(snapshot(), row(master_product_id="999"), "product")["detail_status"] == "identity_mismatch"
    failure = parse_snapshot(snapshot(status=403), row(), "product")
    assert failure["store_id"] == failure["zone_slug"] == ""


def test_missing_description_is_distinct_from_not_found_and_error():
    assert parse_snapshot(snapshot(text="Agua Prueba 500 ml\nAgregar"), row())["detail_status"] == "no_description"
    assert parse_snapshot(snapshot(status=404), row())["detail_status"] == "not_found"
    assert parse_snapshot(snapshot(error="TimeoutError"), row())["detail_status"] == "error"
    assert parse_snapshot(snapshot(status=500), row())["detail_status"] == "error"


@pytest.mark.parametrize("evidence", [snapshot(status=403), snapshot(status=429),
    snapshot(text="Verifica que eres humano"), snapshot(text="¿Eres mayor de edad?"),
    snapshot(blocked_reason="session authorization required")])
def test_access_controls_record_blocked(evidence):
    result = parse_snapshot(evidence, row())
    assert result["detail_status"] == "blocked" and not result["product_information"]


def test_truncated_expansion_is_not_complete_capture():
    result = parse_snapshot(snapshot(text="Información del producto\nAgua mineral... Ver más"), row())
    assert result["detail_status"] == "truncated" and result["product_information"] == ""


def test_inline_expand_control_is_excluded_from_description():
    assert parse_information_text("Información del producto\nAgua mineral. Ver menos")["product_information"] == "Agua mineral."


def test_store_named_recommendation_heading_ends_product_text():
    parsed = parse_information_text("Información del producto\nAgua mineral.\nProductos similares en Makro\nOtra agua 200 ml")
    assert parsed["product_information"] == "Agua mineral."


def test_ssr_fallback_remains_distinct_from_unsuccessful_click():
    evidence = snapshot(text="Información del producto\nAgua... Ver más",
                        ssr_primary_product={"id": "123", "storeId": "15", "masterProductId": "456",
                                             "name": "Agua Prueba 500 ml", "description": "Agua mineral completa."})
    result = parse_snapshot(evidence, row(), "product")
    assert result["detail_status"] == "truncated" and not result["product_information"]
    assert result["ssr_product_information"] == "Agua mineral completa."
    assert result["ssr_information_method"] == "next_data_pdp_primary_product_description"
    assert not parse_snapshot(evidence, row(store_id="99"))["ssr_product_information"]


def test_unverified_location_does_not_get_observation_join():
    assert parse_snapshot(snapshot(location_verified=False), row())["detail_status"] == "location_unverified"
    zone = {"lat": 4.65, "lng": -74.1}
    assert location_matches({**zone, "autoLocation": False}, zone)
    assert not location_matches({**zone, "autoLocation": True}, zone)
    assert not location_matches({"lat": 4.66, "lng": -74.1, "autoLocation": False}, zone)


def test_primary_parser_does_not_take_description_from_additional_store():
    primary = {"id": "123", "storeId": 15, "description": "PRIMARY"}
    payload = {"props": {"pageProps": {"location": {"autoLocation": True}, "fallback": {
        '@"pdp",456,#lng:1,lat:2,,': {"primaryStore": {"product": primary},
            "additionalStores": [{"product": {"id": "123", "storeId": 16, "description": "OTHER"}}]}}}}}
    assert pdp_primary(payload)[0] == primary


def test_passive_json_capture_redacts_query_and_never_reads_body():
    class Response:
        url = "https://www.rappi.com.co/api/product-detail?token=secret&lat=1"
        status = 200
        request = SimpleNamespace(method="GET", resource_type="fetch")

        async def all_headers(self):
            return {"content-type": "application/json; charset=utf-8"}

        async def body(self):
            raise AssertionError("passive metadata capture must not read response bodies")

    records = []
    allowed = {"www.rappi.com.co", "rappi.com.co", "services.grability.rappi.com"}
    asyncio.run(_record_passive_json_response(Response(), allowed, records))
    assert records[0]["url_without_query"] == "https://www.rappi.com.co/api/product-detail"
    assert records[0]["response_body_saved"] is False
    assert "body_text" not in records[0]

    offsite = Response()
    offsite.url = "https://example.com/api/product-detail"
    asyncio.run(_record_passive_json_response(offsite, allowed, records))
    assert len(records) == 1


def test_passive_json_capture_sanitizes_errors_and_enforces_cap():
    class Response:
        url = "https://www.rappi.com.co/api/product-detail?token=secret"

        async def all_headers(self):
            raise RuntimeError("request failed for https://host/path?token=secret")

    records = [{}] * (100 - 1)
    asyncio.run(_record_passive_json_response(
        Response(), {"www.rappi.com.co"}, records))
    assert len(records) == 100
    assert records[-1]["passive_capture_error"] == "RuntimeError"
    assert "secret" not in json.dumps(records[-1])
    asyncio.run(_record_passive_json_response(
        Response(), {"www.rappi.com.co"}, records))
    assert len(records) == 100


def test_api_only_input_produces_replayable_gap_without_browser(tmp_path):
    source = tmp_path / "input.csv"
    data = row(source_url="https://services.grability.rappi.com/api/search")
    with source.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(data))
        writer.writeheader()
        writer.writerow(data)
    path = asyncio.run(run(source, tmp_path / "output", delay=0))
    with path.open(encoding="utf-8-sig") as stream:
        result = next(csv.DictReader(stream))
    assert result["detail_status"] == "no_source_url"
    evidence = json.loads(Path(result["detail_evidence_path"]).read_text())
    assert evidence["input"] == data
    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    assert manifest["input_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert manifest["output_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    evidence_path = Path(result["detail_evidence_path"])
    assert manifest["evidence_sha256"][evidence_path.name] == hashlib.sha256(evidence_path.read_bytes()).hexdigest()


def test_browser_lifecycle_and_global_stop_after_access_challenge(tmp_path, monkeypatch):
    from rappi_co.collect import product_details
    calls = CounterForTest()

    class Page:
        async def route(self, *args):
            pass

        def on(self, *args):
            pass

    class Context:
        async def new_page(self):
            return Page()

        async def close(self):
            calls.context_closed += 1

    class Browser:
        async def new_context(self, **kwargs):
            return Context()

        async def close(self):
            calls.browser_closed += 1

    class Playwright:
        chromium = None

        def __init__(self):
            self.chromium = self

        async def launch(self, **kwargs):
            return Browser()

        async def stop(self):
            calls.playwright_stopped += 1

    class Manager:
        async def start(self):
            return Playwright()

    async def blocked_capture(*args):
        calls.visits += 1
        return snapshot(status=403)

    monkeypatch.setitem(sys.modules, "playwright.async_api", SimpleNamespace(async_playwright=Manager))
    monkeypatch.setattr(product_details, "_capture", blocked_capture)
    monkeypatch.setattr(product_details, "_zone", lambda r: None)
    source = tmp_path / "input.csv"
    data = row(product_url="https://www.rappi.com.co/p/agua-prueba-456")
    with source.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(data))
        writer.writeheader()
        writer.writerows([data, {**data, "product_id": "124"}])
    path = asyncio.run(run(source, tmp_path / "output", delay=0))
    with path.open(encoding="utf-8-sig") as stream:
        results = list(csv.DictReader(stream))
    assert [r["detail_status"] for r in results] == ["blocked", "skipped_after_block"]
    assert calls.visits == calls.context_closed == calls.browser_closed == calls.playwright_stopped == 1


class CounterForTest:
    visits = context_closed = browser_closed = playwright_stopped = 0
