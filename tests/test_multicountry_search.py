import csv
import json

import httpx
import pytest

from rappi_co.collect import search as collector
from rappi_co.parsers.search_api import search


def _response():
    return {
        "stores": [{
            "store_id": "s1",
            "store_type": "market",
            "store_name": "Store",
            "parent_store_type": "retail",
            "products": [{
                "product_id": "p1",
                "name": "Marlboro Rojo 20 Und",
                "price": 75,
                "real_price": 80,
                "is_available": True,
                "in_stock": True,
                "category_name": "Cigarrillos",
            }],
        }],
    }


def test_non_colombia_prices_are_local_not_cop(tmp_path, monkeypatch):
    calls = []

    def fake_search(*args, **kwargs):
        calls.append(kwargs)
        return _response()

    monkeypatch.setattr(collector, "search", fake_search)
    items_path, _ = collector.run(
        "centro-bellas-artes", ["cigarrillos"], tmp_path, country="mx",
        min_delay=0, max_delay=0,
    )
    with open(items_path, encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["country_code"] == "mx" and row["currency"] == "MXN"
    assert row["price_local"] == "75.0"
    assert row["price_cop"] == ""
    assert row["unit_price_local"] == ""
    assert calls[0]["url"].startswith("https://services.mxgrability.rappi.com/")


def test_study_collection_preserves_all_source_terms_and_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "search", lambda *args, **kwargs: _response())
    items_path, _ = collector.run(
        "centro-bellas-artes", ["vapeador", "cigarrillos"], tmp_path,
        min_delay=0, max_delay=0, country="mx",
    )
    with open(items_path, encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["source_term"] == "vapeador"
    assert row["source_terms"] == "vapeador|cigarrillos"
    manifest_path = items_path.with_name(items_path.name.replace("search_items_", "search_manifest_"))
    manifest_path = manifest_path.with_suffix(".json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert manifest["queries"] == ["vapeador", "cigarrillos"]
    assert manifest["items"] == items_path.name
    assert [entry["raw_file"] for entry in manifest["term_results"]] == [
        "001_vapeador.json.gz", "002_cigarrillos.json.gz"]


def test_sanitized_query_collisions_keep_both_raw_responses(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "search", lambda *args, **kwargs: _response())
    items_path, _ = collector.run(
        "centro-bellas-artes", ["l&m", "l m"], tmp_path,
        min_delay=0, max_delay=0, country="mx",
    )
    manifest_path = items_path.with_name(items_path.name.replace("search_items_", "search_manifest_"))
    manifest_path = manifest_path.with_suffix(".json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_files = sorted((tmp_path / manifest["raw_directory"]).glob("*.json.gz"))
    assert [path.name for path in raw_files] == ["001_l_m.json.gz", "002_l_m.json.gz"]


def test_invalid_later_payload_never_writes_complete_manifest(tmp_path, monkeypatch):
    responses = iter((_response(), {}))
    monkeypatch.setattr(collector, "search", lambda *args, **kwargs: next(responses))
    with pytest.raises(RuntimeError, match="unexpected JSON payload"):
        collector.run(
            "centro-bellas-artes", ["vapeador", "cigarrillos"], tmp_path,
            min_delay=0, max_delay=0, country="mx",
        )
    assert not list(tmp_path.glob("search_manifest_*.json"))
    assert not list(tmp_path.glob("search_items_*.csv"))


def test_legacy_positional_delays_keep_original_schema(tmp_path, monkeypatch):
    calls = []

    def fake_search(*args, **kwargs):
        calls.append(kwargs)
        return _response()

    monkeypatch.setattr(collector, "search", fake_search)
    monkeypatch.setattr(collector, "_profile", lambda country: (_ for _ in ()).throw(
        AssertionError("legacy mode must not load study profiles")))
    items_path, _ = collector.run(
        "calle-19-centro", ["cigarrillos"], tmp_path, 0, 0,
    )
    with open(items_path, encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert "country_code" not in row
    assert row["price_cop"] == "75.0"
    assert "url" not in calls[0]
    raw_directories = list(tmp_path.glob("search_raw_*"))
    assert len(raw_directories) == 1
    assert [path.name for path in raw_directories[0].glob("*.json.gz")] == [
        "cigarrillos.json.gz"]


@pytest.mark.parametrize("status", [401, 403])
def test_access_denial_stops_without_retry(status):
    calls = 0

    def denied(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status, request=request)

    with httpx.Client(transport=httpx.MockTransport(denied)) as client:
        with pytest.raises(RuntimeError, match="authorized session or retry later"):
            search("cigarrillos", 0, 0, client=client)
    assert calls == 1


def test_html_challenge_is_not_treated_as_data():
    def challenge(request):
        return httpx.Response(200, text="<html>challenge</html>", request=request)

    with httpx.Client(transport=httpx.MockTransport(challenge)) as client:
        with pytest.raises(RuntimeError, match="non-JSON response"):
            search("cigarrillos", 0, 0, client=client)


@pytest.mark.parametrize("payload", [{}, {"stores": {}}, []])
def test_json_error_or_challenge_shape_is_not_treated_as_data(payload):
    def invalid(request):
        return httpx.Response(200, json=payload, request=request)

    with httpx.Client(transport=httpx.MockTransport(invalid)) as client:
        with pytest.raises(RuntimeError, match="unexpected JSON payload"):
            search("cigarrillos", 0, 0, client=client)


def test_parser_uses_explicit_country_url():
    requested = []

    def response(request):
        requested.append(str(request.url))
        return httpx.Response(200, json=_response(), request=request)

    url = "https://services.rappi.pe/api/pns-global-search-api/v1/unified-search"
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        search("cigarrillos", -12.13, -77.03, client=client, url=url)
    assert requested == [url]
