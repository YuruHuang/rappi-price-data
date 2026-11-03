"""The country-team command plans first and preserves its collection inputs."""
import csv
import hashlib
import json

import pytest

from rappi_co import run as country_run


def _locations(tmp_path):
    path = tmp_path / "locations.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "country_code", "slug", "lat", "lng", "address", "district", "city",
        ])
        writer.writeheader()
        for index in range(3):
            writer.writerow({"country_code": "co", "slug": f"study-{index}",
                             "lat": 4.60 + index / 100, "lng": -74.08,
                             "address": f"Public study point {index}",
                             "district": "Study district", "city": "Bogotá"})
    return path


def _no_collection(*args, **kwargs):
    pytest.fail("dry run must not invoke a collection runner")


def test_dry_run_uses_default_plans_without_creating_output(tmp_path, monkeypatch, capsys):
    output = tmp_path / "dry-run"
    monkeypatch.setattr(country_run.study, "run_country", _no_collection)
    monkeypatch.setattr(country_run.beverages, "run_country", _no_collection)
    monkeypatch.setattr(country_run.release_update, "collect_and_build", _no_collection)

    assert country_run.main(["--country", "co", "--out", str(output), "--dry-run"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["country_code"] == "co"
    assert report["scope"] == "both"
    assert set(report["plans"]) == {"tobacco", "beverages"}
    assert report["planned_search_requests"] == sum(
        plan["requests"] for plan in report["plans"].values())
    assert not output.exists()


def test_dry_run_combines_three_locations_and_two_query_lists(tmp_path, monkeypatch, capsys):
    locations = _locations(tmp_path)
    output = tmp_path / "dry-run"
    monkeypatch.setattr(country_run.release_update, "collect_and_build", _no_collection)

    assert country_run.main([
        "--country", "co", "--locations-file", str(locations), "--scope", "both",
        "--tobacco-terms", "cigarrillos,vapeador", "--beverage-terms", "agua",
        "--out", str(output), "--dry-run",
    ]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["planned_search_requests"] == 9
    assert report["plans"]["tobacco"]["queries"] == ["cigarrillos", "vapeador"]
    assert report["plans"]["beverages"]["queries"] == ["agua"]
    assert all(len(plan["addresses"]) == 3 for plan in report["plans"].values())
    assert report["input_files"][0]["sha256"] == hashlib.sha256(locations.read_bytes()).hexdigest()
    assert not output.exists()


@pytest.mark.parametrize("country", ["ar", "co", "pe", "mx"])
def test_custom_locations_keep_all_country_and_brand_queries(tmp_path, capsys, country):
    """Changing delivery points must not shrink the country's discovery plan."""
    locations = tmp_path / "locations.csv"
    locations.write_text(
        "slug,address,lat,lng\n"
        "point-a,Public study point A,1,1\n"
        "point-b,Public study point B,2,2\n"
        "point-c,Public study point C,3,3\n", encoding="utf-8")
    output = tmp_path / "planned-only"

    assert country_run.main([
        "--country", country, "--locations-file", str(locations),
        "--scope", "both", "--out", str(output), "--dry-run",
    ]) == 0

    report = json.loads(capsys.readouterr().out)
    for scope, runner in [("tobacco", country_run.study),
                          ("beverages", country_run.beverages)]:
        expected = runner.plan_country(country)["queries"]
        assert report["plans"][scope]["queries"] == expected
        assert report["plans"][scope]["requests"] == 3 * len(expected)

    # The default plan must match the searches used for the published beverages,
    # including each country's brands and regional wording, in its original order.
    provenance = country_run.study.ROOT / "datasets" / "beverages" / f"provenance_{country}.json"
    published = json.loads(provenance.read_text(encoding="utf-8"))["plan"]["queries"]
    current = report["plans"]["beverages"]["queries"]
    assert current == published
    assert report["plans"]["beverages"]["config_version"] == 1
    assert not output.exists()


def test_terms_file_is_loaded_for_selected_scope(tmp_path, capsys):
    terms = tmp_path / "terms.txt"
    terms.write_text("agua\nagua mineral\nagua\n", encoding="utf-8")
    output = tmp_path / "dry-run"

    assert country_run.main([
        "--country", "co", "--scope", "beverages", "--terms-file", str(terms),
        "--out", str(output), "--dry-run",
    ]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["plans"]["beverages"]["queries"] == ["agua", "agua mineral"]
    assert report["planned_search_requests"] == 4
    assert report["input_files"][0]["sha256"] == hashlib.sha256(terms.read_bytes()).hexdigest()
    assert not output.exists()


def test_both_scopes_forward_only_selected_country_to_release(tmp_path, monkeypatch, capsys):
    locations = _locations(tmp_path)
    output = tmp_path / "collection"
    calls = []

    def fake_release(out, minimum, maximum, **kwargs):
        calls.append((out, minimum, maximum, kwargs))
        return {"status": "verified_updated_country_workbooks"}

    monkeypatch.setattr(country_run.release_update, "collect_and_build", fake_release)

    assert country_run.main([
        "--country", "co", "--scope", "both", "--locations-file", str(locations),
        "--tobacco-terms", "cigarrillos", "--beverage-terms", "agua,cerveza",
        "--out", str(output), "--collect",
    ]) == 0

    assert calls == [(output, 1.0, 3.0, {
        "resume": False, "countries": ["co"], "locations_file": locations,
        "tobacco_terms": ["cigarrillos"], "beverage_terms": ["agua", "cerveza"],
    })]
    assert json.loads(capsys.readouterr().out)["status"] == "verified_updated_country_workbooks"


@pytest.mark.parametrize("arguments", [
    ["--scope", "both", "--terms", "agua"],
    ["--scope", "tobacco", "--beverage-terms", "agua"],
    ["--scope", "beverages", "--tobacco-terms", "cigarrillos"],
    ["--scope", "tobacco", "--terms", "a", "--tobacco-terms", "b"],
    ["--scope", "both", "--address", "centro-plaza-bolivar"],
    ["--scope", "beverages", "--terms", ", ,"],
    ["--scope", "beverages", "--resume"],
    ["--min-delay", "-1"],
    ["--min-delay", "4", "--max-delay", "3"],
    ["--min-delay", "nan"],
    ["--max-delay", "inf"],
    ["--min-delay", "inf", "--max-delay", "inf"],
])
def test_invalid_arguments_fail_before_output_creation(tmp_path, monkeypatch, arguments):
    output = tmp_path / "invalid"
    monkeypatch.setattr(country_run.study, "run_country", _no_collection)
    monkeypatch.setattr(country_run.beverages, "run_country", _no_collection)
    monkeypatch.setattr(country_run.release_update, "collect_and_build", _no_collection)

    with pytest.raises(SystemExit) as error:
        country_run.main(["--country", "co", "--out", str(output), "--dry-run", *arguments])

    assert error.value.code == 2
    assert not output.exists()


def test_query_text_and_file_cannot_be_mixed(tmp_path):
    path = tmp_path / "terms.txt"
    path.write_text("agua\n", encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        country_run.main(["--country", "co", "--scope", "beverages", "--terms", "agua",
                          "--terms-file", str(path), "--out", str(tmp_path / "invalid"), "--dry-run"])
    assert error.value.code == 2
