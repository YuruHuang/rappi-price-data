"""Run real collection, classification and workbook exports behind a fake search boundary."""
import csv
import hashlib
import json
from pathlib import Path

import httpx
from openpyxl import load_workbook
import pytest

from rappi_co import release_update
from rappi_co import run as country_run
from rappi_co.collect import search as collector


def _locations_file(tmp_path, include_peru):
    rows = [
        {"country_code": "co", "slug": "co-medellin", "lat": 6.25, "lng": -75.56,
         "address": "Public study point one", "district": "Study district", "city": "Medellin"},
        {"country_code": "co", "slug": "co-unspecified-city", "lat": 3.45, "lng": -76.53,
         "address": "Public study point two", "district": "Study district", "city": ""},
        {"country_code": "co", "slug": "co-cartagena", "lat": 10.39, "lng": -75.48,
         "address": "Public study point three", "district": "Study district", "city": "Cartagena"},
    ]
    if include_peru:
        rows.append({"country_code": "pe", "slug": "pe-lima", "lat": -12.05, "lng": -77.04,
                     "address": "Public study point four", "district": "Study district", "city": "Lima"})
    path = tmp_path / "locations.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path, rows


def _payload(term):
    names = {
        "cigarrillos": ("001", "Marlboro Rojo 20 Und", "Cigarrillos"),
        "agua": ("002", "Agua natural 500 ml", "Agua"),
        "gaseosa": ("003", "Gaseosa Original 500 ml", "Gaseosas"),
        "cerveza": ("004", "Cerveza lager 330 ml", "Cervezas"),
    }
    product_id, name, category = names[term]
    return {"stores": [{
        "store_id": "0007", "store_type": "market", "store_name": "Fixture shop",
        "parent_store_type": "retail", "products": [{
            "product_id": product_id, "name": name, "price": 100, "real_price": 120,
            "is_available": True, "in_stock": True, "category_name": category,
            "quantity": 500 if term in {"agua", "gaseosa"} else 330,
            "unit_type": "ml", "alcoholic_beverage": term == "cerveza",
        }],
    }]}


def _worksheet_rows(book, sheet):
    rows = book[sheet].iter_rows(values_only=True)
    headers = next(rows)
    assert len(headers) == len(set(headers)), "exported headers must not duplicate country_code"
    return [dict(zip(headers, values)) for values in rows]


@pytest.mark.parametrize("include_peru", [False, True], ids=["one-country-three-points", "two-countries"])
def test_custom_locations_real_pipeline_to_verified_country_workbooks(tmp_path, monkeypatch, include_peru):
    """Only the remote search is replaced; all local pipeline stages run unchanged."""
    locations_file, locations = _locations_file(tmp_path, include_peru)
    countries = ["co", "pe"] if include_peru else ["co"]
    calls = []

    def fake_search(term, lat, lng, **kwargs):
        calls.append((term, lat, lng, kwargs["url"]))
        return _payload(term)

    monkeypatch.setattr(collector, "search", fake_search)
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("unexpected live network request"))
    out = tmp_path / "release"

    if include_peru:
        result = release_update.collect_and_build(
            out, 0, 0, countries=countries, locations_file=locations_file,
            tobacco_terms=["cigarrillos"], beverage_terms=["agua", "gaseosa", "cerveza"],
        )
    else:
        tobacco_file = tmp_path / "tobacco.txt"
        tobacco_file.write_text("cigarrillos\n", encoding="utf-8")
        beverage_file = tmp_path / "beverages.csv"
        beverage_file.write_text("term\nagua\ngaseosa\ncerveza\n", encoding="utf-8")
        assert country_run.main([
            "--country", "co", "--scope", "both", "--locations-file", str(locations_file),
            "--tobacco-terms-file", str(tobacco_file), "--beverage-terms-file", str(beverage_file),
            "--out", str(out), "--collect", "--min-delay", "0", "--max-delay", "0",
        ]) == 0
        result = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert len(result["extra_input_snapshots"]) == 2
        for source, snapshot_record in zip((tobacco_file, beverage_file), result["extra_input_snapshots"], strict=True):
            assert snapshot_record["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
            assert Path(snapshot_record["path"]).read_bytes() == source.read_bytes()

    assert result["status"] == "verified_updated_country_workbooks"
    assert [entry["country_code"] for entry in result["countries"]] == countries
    assert len(calls) == len(locations) * 4
    assert {(lat, lng) for _, lat, lng, _ in calls} == {(row["lat"], row["lng"]) for row in locations}
    assert result["selection"]["location_counts"] == ({"co": 3, "pe": 1} if include_peru else {"co": 3})
    snapshot = out / "inputs" / "locations.csv"
    assert snapshot.read_bytes() == locations_file.read_bytes()
    assert result["input_snapshot"]["sha256"] == hashlib.sha256(locations_file.read_bytes()).hexdigest()
    assert not (out / "update_state.json").exists()

    for country in countries:
        expected_locations = [row for row in locations if row["country_code"] == country]
        expected_by_slug = {row["slug"]: row for row in expected_locations}
        name = "colombia" if country == "co" else "peru"
        book = load_workbook(out / "country_products" / f"{name}.xlsx", read_only=True, data_only=False)
        try:
            assert book.sheetnames == list(release_update.SHEETS)
            technical = dict(list(book["Technical specifications"].iter_rows(values_only=True))[1:])
            assert technical["Delivery locations"] == str(len(expected_locations))
            for sheet in release_update.SHEETS[1:]:
                rows = _worksheet_rows(book, sheet)
                assert len(rows) == len(expected_locations), (country, sheet, rows)
                assert {row["zone_slug"] for row in rows} == set(expected_by_slug)
                assert {row["country_code"] for row in rows} == {country}
                assert {row["currency"] for row in rows} == ({"COP"} if country == "co" else {"PEN"})
                for row in rows:
                    location = expected_by_slug[row["zone_slug"]]
                    assert row["city"] == (location["city"] or None), (sheet, row)
                    assert row["store_id"] == "0007"
        finally:
            book.close()

    saved = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert saved["status"] == "verified_updated_country_workbooks"
    assert saved["selection"]["countries"] == countries
    assert saved["selection"]["location_counts"]["co"] == 3
    raw_manifests = list((out / "raw").glob("*/co/raw/*/search_manifest_*.json"))
    assert len(raw_manifests) == 6
    for path in raw_manifests:
        record = json.loads(path.read_text(encoding="utf-8"))
        location = next(row for row in locations if row["slug"] == record["address"])
        assert record["latitude"] == location["lat"]
        assert record["longitude"] == location["lng"]
        assert record["city"] == location["city"]
        assert record["complete"] is True


@pytest.mark.parametrize("empty_mode", ["all", "one"], ids=["all-locations-empty", "one-location-empty"])
def test_valid_empty_searches_preserve_locations_and_complete_country_package(tmp_path, monkeypatch, empty_mode):
    locations_file, locations = _locations_file(tmp_path, False)
    empty_lat = locations[1]["lat"]

    def fake_search(term, lat, lng, **kwargs):
        return {"stores": []} if empty_mode == "all" or lat == empty_lat else _payload(term)

    monkeypatch.setattr(collector, "search", fake_search)
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("unexpected live network request"))
    out = tmp_path / "release"

    result = release_update.collect_and_build(
        out, 0, 0, countries=["co"], locations_file=locations_file,
        tobacco_terms=["cigarrillos"], beverage_terms=["agua", "gaseosa", "cerveza"],
    )

    assert result["status"] == "verified_updated_country_workbooks"
    assert result["selection"]["location_counts"] == {"co": 3}
    assert len(result["countries"][0]["locations"]) == 3
    expected_rows = 0 if empty_mode == "all" else 2
    assert set(result["countries"][0]["rows"].values()) == {expected_rows}
    book = load_workbook(out / "country_products" / "colombia.xlsx", read_only=True, data_only=False)
    try:
        assert book.sheetnames == list(release_update.SHEETS)
        technical = dict(list(book["Technical specifications"].iter_rows(values_only=True))[1:])
        assert technical["Delivery locations"] == "3"
        assert technical["Collection dates"]
        assert len(technical["Collection dates"].split(", ")[0]) == 8
        for sheet in release_update.SHEETS[1:]:
            rows = _worksheet_rows(book, sheet)
            assert len(rows) == expected_rows
            assert all(row["zone_slug"] != "co-unspecified-city" for row in rows)
    finally:
        book.close()
    raw_manifests = [json.loads(path.read_text(encoding="utf-8"))
                     for path in (out / "raw").glob("*/co/raw/*/search_manifest_*.json")]
    assert len(raw_manifests) == 6
    expected_empty = 6 if empty_mode == "all" else 2
    assert sum(record["collection_outcome"] == "no_results" for record in raw_manifests) == expected_empty
    assert all(record["complete"] is True for record in raw_manifests)
    assert not (out / "update_state.json").exists()


def test_country_cli_resume_rejects_changed_query_file_even_when_queries_are_unchanged(tmp_path, monkeypatch):
    locations_file, _ = _locations_file(tmp_path, False)
    tobacco_file = tmp_path / "tobacco.txt"
    tobacco_file.write_text("cigarrillos\n", encoding="utf-8")
    beverage_file = tmp_path / "beverages.csv"
    beverage_file.write_text("term\nagua\ngaseosa\ncerveza\n", encoding="utf-8")
    calls = []

    def fake_search(term, lat, lng, **kwargs):
        calls.append(term)
        return _payload(term)

    def interrupted_packaging(*args, **kwargs):
        raise RuntimeError("simulated interruption after country collection")

    monkeypatch.setattr(collector, "search", fake_search)
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("unexpected live network request"))
    monkeypatch.setattr(release_update, "_build_country", interrupted_packaging)
    out = tmp_path / "release"
    arguments = [
        "--country", "co", "--scope", "both", "--locations-file", str(locations_file),
        "--tobacco-terms-file", str(tobacco_file), "--beverage-terms-file", str(beverage_file),
        "--out", str(out), "--collect", "--min-delay", "0", "--max-delay", "0",
    ]
    with pytest.raises(RuntimeError, match="simulated interruption"):
        country_run.main(arguments)
    assert len(calls) == 12
    state = json.loads((out / "update_state.json").read_text(encoding="utf-8"))
    assert set(state["completed"]) == {"co"}
    assert len(state["extra_input_snapshots"]) == 2

    # Normalization still produces the same query list; the original file's exact
    # byte hash is separately part of the resumable selection.
    tobacco_file.write_text(" cigarrillos \n\n", encoding="utf-8")
    calls.clear()
    with pytest.raises(SystemExit) as error:
        country_run.main([*arguments, "--resume"])
    assert error.value.code == 2
    assert calls == []
    assert not (out / "manifest.json").exists()
