import csv
import json

import pytest

from rappi_co.locations import (
    LocationError, load_location_file, location_file_record, validate_location_scope,
)


def _row(**changes):
    return {"country_code": "co", "slug": "point-a", "lat": 4.59806,
            "lng": -74.07609, "address": "Carrera 7 #10-47", **changes}


def _json(tmp_path, rows, name="points.json"):
    path = tmp_path / name
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_json_supports_more_than_two_points(tmp_path):
    path = _json(tmp_path, [_row(slug=f"point-{i}") for i in range(25)])
    rows = load_location_file(path, "co")
    assert len(rows) == 25
    assert rows[0] == {**_row(), "district": "", "slug": "point-0"}


@pytest.mark.parametrize("suffix,delimiter", [(".csv", ","), (".tsv", "\t")])
def test_delimited_aliases_bom_and_quoted_address(tmp_path, suffix, delimiter):
    path = tmp_path / f"points{suffix}"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerow([" Country ", "Location ID", "Latitude", "Longitude", "Full Address", "City"])
        writer.writerow(["CO", "point-a", "4.598060", "-74.076090", "Carrera 7 #10-47, Bogotá", "Bogotá"])
        writer.writerow(["", "", "", "", "", ""])
    row = load_location_file(path)[0]
    assert row["country_code"] == "co"
    assert row["lat"] == 4.59806
    assert row["address"] == "Carrera 7 #10-47, Bogotá"
    assert row["city"] == "Bogotá"


@pytest.mark.parametrize("key", ["zones", "locations"])
@pytest.mark.parametrize("suffix", [".json", ".yaml", ".yml"])
def test_structured_mapping_and_top_level_country(tmp_path, key, suffix):
    payload = {"country": "co", key: [{"slug": "a", "latitude": 0, "lon": 0, "full_address": "Public place"}]}
    path = tmp_path / f"points{suffix}"
    if suffix == ".json":
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        import yaml
        path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    assert load_location_file(path)[0] == {
        "country_code": "co", "slug": "a", "lat": 0.0, "lng": 0.0,
        "address": "Public place", "district": ""}


def test_excel_reads_first_sheet(tmp_path):
    from openpyxl import Workbook
    path = tmp_path / "points.xlsx"
    book = Workbook()
    book.active.append(["slug", "latitude", "lon", "address", "district"])
    book.active.append(["a", -12.1, -77.1, "Verified landmark", "District"])
    book.active.append([None, None, None, None, None])
    other = book.create_sheet("Ignored")
    other.append(["not location data"])
    book.save(path)
    assert load_location_file(path, "pe") == [
        {"slug": "a", "lat": -12.1, "lng": -77.1, "address": "Verified landmark", "district": "District"}]


def test_country_filter_retains_untagged_and_filters_tagged(tmp_path):
    untagged = _row(slug="untagged")
    del untagged["country_code"]
    path = _json(tmp_path, [_row(), _row(country_code="mx", slug="mx"), untagged])
    assert [row["slug"] for row in load_location_file(path, "co")] == ["point-a", "untagged"]
    assert load_location_file(_json(tmp_path, [_row(country_code="mx")]), "ar") == []


def test_slug_generation_is_deterministic_and_coordinates_distinguish_points(tmp_path):
    row = _row(address="Plaza de Bolívar")
    del row["slug"]
    path = _json(tmp_path, [row, {**row, "lat": 4.6}])
    slugs = [point["slug"] for point in load_location_file(path)]
    assert slugs[0].startswith("plaza-de-bolivar-")
    assert slugs == [point["slug"] for point in load_location_file(path)]
    assert slugs[0] != slugs[1]


@pytest.mark.parametrize("field,value", [
    ("lat", "NaN"), ("lng", "inf"), ("lat", True), ("lng", False),
    ("lat", 90.1), ("lng", -180.1), ("lat", "bad"), ("lng", ""),
])
def test_invalid_coordinates_fail_even_on_filtered_country(tmp_path, field, value):
    path = _json(tmp_path, [_row(country_code="mx", **{field: value})])
    with pytest.raises(LocationError):
        load_location_file(path, "co")


@pytest.mark.parametrize("field", ["lat", "lng", "address"])
def test_required_fields(tmp_path, field):
    row = _row()
    del row[field]
    with pytest.raises(LocationError, match="required"):
        load_location_file(_json(tmp_path, [row]))


@pytest.mark.parametrize("code", ["us", "Colombia", 1])
def test_unsupported_country_rejected(tmp_path, code):
    with pytest.raises(LocationError, match="country"):
        load_location_file(_json(tmp_path, [_row(country_code=code)]))


def test_duplicate_slugs_rejected_within_country_but_allowed_across_countries(tmp_path):
    with pytest.raises(LocationError, match="duplicate"):
        load_location_file(_json(tmp_path, [_row(), _row(lat=4.6)]))
    assert len(load_location_file(_json(tmp_path, [_row(), _row(country_code="mx")]))) == 2


def test_tagged_and_untagged_slug_collision_on_selection(tmp_path):
    untagged = _row()
    del untagged["country_code"]
    with pytest.raises(LocationError, match="duplicate"):
        load_location_file(_json(tmp_path, [_row(), untagged]), "co")


@pytest.mark.parametrize("slug", ["../elsewhere", "/tmp/point", ".", "a/b", "a\\b", "a space"])
def test_unsafe_slug_rejected(tmp_path, slug):
    with pytest.raises(LocationError, match="slug"):
        load_location_file(_json(tmp_path, [_row(slug=slug)]))


def test_conflicting_aliases_rejected(tmp_path):
    with pytest.raises(LocationError, match="conflicting"):
        load_location_file(_json(tmp_path, [_row(latitude=1)]))
    assert load_location_file(_json(tmp_path, [_row(latitude="4.59806")]))[0]["lat"] == 4.59806


@pytest.mark.parametrize("payload", [[], {}, {"zones": []}, {"zones": [], "locations": []}, ["bad"]])
def test_empty_or_wrong_shape(tmp_path, payload):
    with pytest.raises(LocationError):
        load_location_file(_json(tmp_path, payload))


def test_bad_csv_headers_and_extra_columns(tmp_path):
    path = tmp_path / "points.csv"
    path.write_text("lat,lat,address,lng\n1,2,a,3\n", encoding="utf-8")
    with pytest.raises(LocationError, match="duplicate"):
        load_location_file(path)
    path.write_text("lat,address,lng\n1,a,3,unexpected\n", encoding="utf-8")
    with pytest.raises(LocationError, match="more values"):
        load_location_file(path)


def test_missing_and_unsupported_file(tmp_path):
    with pytest.raises(LocationError, match="cannot read"):
        load_location_file(tmp_path / "missing.csv")
    path = tmp_path / "points.txt"
    path.write_text("data", encoding="utf-8")
    with pytest.raises(LocationError, match="supported"):
        load_location_file(path)


def test_invalid_filter_rejected(tmp_path):
    with pytest.raises(LocationError, match="country"):
        load_location_file(_json(tmp_path, [_row()]), "us")


def test_location_scope_accepts_untagged_single_country(tmp_path):
    row = _row()
    del row["country_code"]
    validate_location_scope(_json(tmp_path, [row]), ["co"])


def test_location_scope_requires_all_selected_countries_and_explicit_tags(tmp_path):
    path = _json(tmp_path, [_row()])
    with pytest.raises(LocationError, match="no delivery points.*mx"):
        validate_location_scope(path, ["co", "mx"])
    row = _row(slug="untagged")
    del row["country_code"]
    with pytest.raises(LocationError, match="require country_code"):
        validate_location_scope(_json(tmp_path, [_row(), row]), ["co", "mx"])
    validate_location_scope(_json(tmp_path, [_row(), _row(country_code="mx")]), ["co", "mx"])


@pytest.mark.parametrize("countries", [[], ["co", "co"], ["us"]])
def test_bad_scope_selection(tmp_path, countries):
    with pytest.raises(LocationError):
        validate_location_scope(_json(tmp_path, [_row()]), countries)


def test_location_file_hash_changes_with_contents(tmp_path):
    import hashlib
    path = _json(tmp_path, [_row()])
    before = location_file_record(path)
    assert before == {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    path.write_text(json.dumps([_row(slug="changed")]), encoding="utf-8")
    assert location_file_record(path)["sha256"] != before["sha256"]
