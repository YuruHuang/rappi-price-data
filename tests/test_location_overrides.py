"""Location overrides must reach plans, requests, and saved-run validation."""
import csv
import json
import sys

import pytest

from rappi_co import beverages, release_update, study
from rappi_co.collect import search as collector


def _location(slug, lat=4.61, lng=-74.08, country="co"):
    return {
        "country_code": country,
        "slug": slug,
        "lat": lat,
        "lng": lng,
        "address": f"Public study point {slug}",
        "district": "Study district",
    }


def _locations_file(tmp_path, rows):
    path = tmp_path / "locations.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _search_payload():
    return {"stores": [{"store_id": "001", "store_name": "Study store", "products": [
        {"product_id": "product-one", "name": "Agua 500 ml", "price": 100,
         "quantity": 500, "unit_type": "ml", "presentation": "1 x 500 ml"},
    ]}]}


@pytest.mark.parametrize("runner", [study, beverages])
def test_custom_plan_accepts_more_than_two_points(tmp_path, runner):
    path = _locations_file(tmp_path, [
        _location("point-one", 4.60),
        _location("point-two", 4.65),
        _location("point-three", 4.70),
    ])

    plan = runner.plan_country("co", terms=["query one", "query two"], locations_file=path)

    assert [zone["slug"] for zone in plan["addresses"]] == [
        "point-one", "point-two", "point-three",
    ]
    assert [zone["lat"] for zone in plan["addresses"]] == [4.60, 4.65, 4.70]
    assert plan["requests"] == 6


@pytest.mark.parametrize("runner", [study, beverages])
def test_custom_plan_filters_by_custom_slug(tmp_path, runner):
    path = _locations_file(tmp_path, [_location("first"), _location("second", 4.65)])

    plan = runner.plan_country("co", addresses=["second"], terms=["query"], locations_file=path)

    assert [zone["slug"] for zone in plan["addresses"]] == ["second"]
    assert plan["addresses"][0]["lat"] == 4.65
    assert plan["requests"] == 1
    with pytest.raises(ValueError):
        runner.plan_country("co", addresses=["centro-plaza-bolivar"], locations_file=path)


@pytest.mark.parametrize("runner", [study, beverages])
def test_multicountry_file_uses_only_requested_country(tmp_path, runner):
    path = _locations_file(tmp_path, [
        _location("co-point"),
        _location("pe-point", -12.10, -77.03, "pe"),
    ])

    plan = runner.plan_country("pe", terms=["query"], locations_file=path)

    assert [zone["slug"] for zone in plan["addresses"]] == ["pe-point"]
    assert plan["addresses"][0]["lat"] == -12.10
    with pytest.raises(ValueError):
        runner.plan_country("ar", terms=["query"], locations_file=path)


@pytest.mark.parametrize("runner", [study, beverages])
def test_collect_only_records_custom_coordinates_in_manifest(tmp_path, monkeypatch, runner):
    path = _locations_file(tmp_path, [
        _location("custom-one", 4.6123, -74.0812),
        _location("custom-two", 4.6587, -74.0598),
        _location("custom-three", 4.7012, -74.0456),
    ])
    observed = []

    def fake_search(term, lat, lng, **kwargs):
        observed.append((term, lat, lng))
        return _search_payload()

    monkeypatch.setattr(collector, "search", fake_search)
    data_root = tmp_path / "results"

    runner.run_country("co", terms=["query"], collect_only=True,
                       data_root=data_root, locations_file=path,
                       min_delay=0, max_delay=0)

    assert observed == [
        ("query", 4.6123, -74.0812),
        ("query", 4.6587, -74.0598),
        ("query", 4.7012, -74.0456),
    ]
    manifests = sorted(data_root.glob("co/raw/*/search_manifest_*.json"))
    assert len(manifests) == 3
    records = {json.loads(p.read_text(encoding="utf-8"))["address"]:
               json.loads(p.read_text(encoding="utf-8")) for p in manifests}
    assert records["custom-one"]["latitude"] == 4.6123
    assert records["custom-two"]["longitude"] == -74.0598
    assert records["custom-three"]["complete"] is True


def test_saved_source_rejects_coordinate_change_for_same_slug(tmp_path, monkeypatch):
    path = _locations_file(tmp_path, [_location("same-slug", 4.61, -74.08)])
    monkeypatch.setattr(collector, "search", lambda *args, **kwargs: _search_payload())
    directory = tmp_path / "raw"
    items, _ = collector.run("same-slug", ["query"], directory, country="co",
                             min_delay=0, max_delay=0, locations_file=path)

    assert study._complete_source(directory, "co", "same-slug", ["query"],
                                  expected_zone=_location("same-slug", 4.61, -74.08)) == items
    with pytest.raises(FileNotFoundError):
        study._complete_source(directory, "co", "same-slug", ["query"],
                               expected_zone=_location("same-slug", 4.62, -74.08))


@pytest.mark.parametrize("runner", [study, beverages])
def test_runner_cli_dry_run_uses_locations_file(tmp_path, monkeypatch, capsys, runner):
    path = _locations_file(tmp_path, [_location("terminal-point", 4.635)])
    monkeypatch.setattr(sys, "argv", ["runner", "--country", "co", "--terms", "query",
                                     "--locations-file", str(path), "--dry-run"])
    monkeypatch.setattr(collector, "search", lambda *a, **k: pytest.fail("dry run made a request"))

    assert runner.main() == 0

    plans = json.loads(capsys.readouterr().out)
    assert plans[0]["addresses"][0]["slug"] == "terminal-point"
    assert plans[0]["requests"] == 1


def test_release_cli_dry_run_for_one_country_uses_locations_file(tmp_path, monkeypatch, capsys):
    path = _locations_file(tmp_path, [_location("release-point", 4.635)])
    monkeypatch.setattr(collector, "search", lambda *a, **k: pytest.fail("dry run made a request"))

    assert release_update.main(["--out", str(tmp_path / "release"), "--country", "co",
                                "--locations-file", str(path), "--dry-run"]) == 0

    plans = json.loads(capsys.readouterr().out)
    for scope in ("tobacco", "beverages"):
        assert len(plans[scope]) == 1
        assert plans[scope][0]["country_code"] == "co"
        assert plans[scope][0]["addresses"][0]["slug"] == "release-point"
    assert not (tmp_path / "release").exists()


def test_resume_rejects_changed_location_before_reusing_completed_country(tmp_path, monkeypatch):
    rows = [_location("co-point"), _location("pe-point", -12.10, -77.03, "pe")]
    path = _locations_file(tmp_path, rows)
    out = tmp_path / "release"
    calls = []

    def fake_tobacco(country, **kwargs):
        calls.append(("tobacco", country))
        if country == "pe":
            raise RuntimeError("simulated interrupted collection")
        return {"deliverable": {"manifest": str(tmp_path / f"{country}-tobacco.json")}}

    def fake_beverage(country, **kwargs):
        calls.append(("beverages", country))
        return {"deliverable": {"manifest": str(tmp_path / f"{country}-beverages.json")}}

    monkeypatch.setattr(study, "run_country", fake_tobacco)
    monkeypatch.setattr(beverages, "run_country", fake_beverage)
    with pytest.raises(RuntimeError, match="simulated interrupted"):
        release_update.collect_and_build(out, 0, 0, countries=["co", "pe"], locations_file=path)
    assert (out / "update_state.json").is_file()

    rows[0]["lat"] = 4.62
    _locations_file(tmp_path, rows)
    calls.clear()
    with pytest.raises((ValueError, RuntimeError)):
        release_update.collect_and_build(out, 0, 0, resume=True,
                                         countries=["co", "pe"], locations_file=path)
    assert calls == []
