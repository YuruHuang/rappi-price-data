import json

import pytest
from openpyxl import Workbook

from rappi_co.terms import load_terms_file


def test_text_preserves_order_and_commas(tmp_path):
    path = tmp_path / "terms.txt"
    path.write_text("\ufeff milk \n\nwater\nmilk\ntea, cold\n", encoding="utf-8")
    assert load_terms_file(path) == ["milk", "water", "tea, cold"]


@pytest.mark.parametrize("suffix,contents", [
    (".csv", 'term,notes\n"tea, cold",example\nwater,\n'),
    (".tsv", "search_term\tnotes\ntea, cold\texample\nwater\t\n"),
    (".CSV", " QUERY \n tea \nwater\n"),
])
def test_delimited_formats(tmp_path, suffix, contents):
    path = tmp_path / f"terms{suffix}"
    path.write_text(contents, encoding="utf-8")
    expected = ["tea", "water"] if suffix == ".CSV" else ["tea, cold", "water"]
    assert load_terms_file(path) == expected


@pytest.mark.parametrize("suffix,contents", [
    (".json", '[" water ", "tea", "water"]'),
    (".json", '{"terms": ["water", "tea"]}'),
    (".json", '{"queries": ["water", "tea"]}'),
    (".yaml", "- water\n- tea\n"),
    (".yml", "queries:\n  - water\n  - tea\n"),
    (".yml", "terms:\n  - water\n  - tea\n"),
])
def test_structured_formats(tmp_path, suffix, contents):
    path = tmp_path / f"terms{suffix}"
    path.write_text(contents, encoding="utf-8")
    assert load_terms_file(path) == ["water", "tea"]


def test_xlsx_first_sheet_and_text_validation(tmp_path):
    path = tmp_path / "terms.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.append(["query", "notes"])
    sheet.append([" milk ", "example"])
    sheet.append([None, None])
    sheet.append(["milk", None])
    sheet.append(["tea, cold", None])
    book.create_sheet("ignored").append(["not a query"])
    book.save(path)
    book.close()
    assert load_terms_file(path) == ["milk", "tea, cold"]


def test_alias_columns_must_agree(tmp_path):
    path = tmp_path / "terms.csv"
    path.write_text("term,query\nwater,water\n,tea\n", encoding="utf-8")
    assert load_terms_file(path) == ["water", "tea"]
    path.write_text("term,query\nwater,milk\n", encoding="utf-8")
    with pytest.raises(ValueError, match="conflicting query columns"):
        load_terms_file(path)


@pytest.mark.parametrize("contents,message", [
    ("[]", "empty"),
    ('["water", " "]', "non-empty text"),
    ('["water", 12]', "non-empty text"),
    ('{"terms": "water"}', "expected a list"),
    ('{"unknown": ["water"]}', "mapping needs"),
    ('{"terms": ["water"], "queries": ["tea"]}', "conflict"),
    ("invalid json", "could not read"),
])
def test_invalid_json_queries(tmp_path, contents, message):
    path = tmp_path / "terms.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_terms_file(path)


@pytest.mark.parametrize("contents,message", [
    ("notes\nwater\n", "header needs"),
    ("term,term\nwater,water\n", "duplicate query column"),
    ("term,notes\nwater\n", "expected 2"),
    ("term,notes\n,missing query\n", "no query text"),
    ("term\n", "empty"),
    ("", "table is empty"),
])
def test_invalid_csv(tmp_path, contents, message):
    path = tmp_path / "terms.csv"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_terms_file(path)


def test_xlsx_numeric_query_is_not_silently_coerced(tmp_path):
    path = tmp_path / "terms.xlsx"
    book = Workbook()
    book.active.append(["term"])
    book.active.append([123])
    book.save(path)
    book.close()
    with pytest.raises(ValueError, match="must contain text"):
        load_terms_file(path)


def test_missing_unsupported_and_corrupt_files(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        load_terms_file(tmp_path / "missing.txt")
    path = tmp_path / "terms.pdf"
    path.write_bytes(b"not a supported file")
    with pytest.raises(ValueError, match="unsupported terms format"):
        load_terms_file(path)
    path = tmp_path / "terms.xlsx"
    path.write_bytes(b"not an xlsx archive")
    with pytest.raises(ValueError, match="could not read XLSX"):
        load_terms_file(path)


def test_equal_structured_aliases_are_accepted(tmp_path):
    path = tmp_path / "terms.json"
    path.write_text(json.dumps({"terms": ["water"], "queries": ["water"]}),
                    encoding="utf-8")
    assert load_terms_file(path) == ["water"]
