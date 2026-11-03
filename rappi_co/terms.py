"""Load explicit query lists supplied by country teams.

The file replaces a runner's configured queries for the selected topic. Values
stay as a list, so a query containing a comma remains one query.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

import yaml


_QUERY_COLUMNS = ("term", "query", "search_term")


def _normalize_terms(values: Iterable, label: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values, 1):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label}: query #{index} must be non-empty text")
        term = value.strip()
        if term not in seen:
            seen.add(term)
            result.append(term)
    if not result:
        raise ValueError(f"{label}: query list is empty")
    return result


def _structured_terms(data, label: str) -> list[str]:
    if isinstance(data, dict):
        keys = [key for key in ("terms", "queries") if key in data]
        if not keys:
            raise ValueError(f"{label}: mapping needs a 'terms' or 'queries' list")
        if len(keys) > 1 and data["terms"] != data["queries"]:
            raise ValueError(f"{label}: 'terms' and 'queries' lists conflict")
        data = data[keys[0]]
    if not isinstance(data, list):
        raise ValueError(f"{label}: expected a list of query strings")
    return _normalize_terms(data, label)


def _table_terms(rows: Iterable, label: str) -> list[str]:
    iterator = iter(rows)
    try:
        headers = next(iterator)
    except StopIteration:
        raise ValueError(f"{label}: table is empty") from None
    names = [str(value).strip().casefold() if value is not None else ""
             for value in headers]
    selected = [(i, name) for i, name in enumerate(names) if name in _QUERY_COLUMNS]
    if not selected:
        raise ValueError(
            f"{label}: header needs a term, query, or search_term column"
        )
    if len({name for _, name in selected}) != len(selected):
        raise ValueError(f"{label}: duplicate query column in header")
    values = []
    for line_number, row in enumerate(iterator, 2):
        row = list(row)
        if all(value is None or (isinstance(value, str) and not value.strip())
               for value in row):
            continue
        if len(row) != len(headers):
            raise ValueError(
                f"{label}: row {line_number} has {len(row)} cells; "
                f"expected {len(headers)}"
            )
        candidates = []
        for index, name in selected:
            value = row[index]
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            if not isinstance(value, str):
                raise ValueError(
                    f"{label}: row {line_number} column {name} must contain text"
                )
            candidates.append(value.strip())
        if not candidates:
            raise ValueError(f"{label}: row {line_number} has no query text")
        if len(set(candidates)) > 1:
            raise ValueError(
                f"{label}: row {line_number} has conflicting query columns"
            )
        values.append(candidates[0])
    return _normalize_terms(values, label)


def load_terms_file(path: str | Path) -> list[str]:
    """Read TXT, CSV, TSV, XLSX, JSON, or YAML queries in file order.

    Text files contain one query per nonblank line. CSV, TSV and the first
    worksheet of XLSX files use a ``term``, ``query`` or ``search_term`` column.
    Structured files hold a string list or a mapping with ``terms``/``queries``.
    Leading/trailing whitespace is stripped and exact duplicates are removed.
    Conflicting alias columns or mapping keys are rejected rather than guessed.
    """
    source = Path(path)
    label = str(source)
    if not source.is_file():
        raise ValueError(f"terms file not found: {source}")
    extension = source.suffix.casefold()
    supported = {".txt", ".csv", ".tsv", ".xlsx", ".json", ".yaml", ".yml"}
    if extension not in supported:
        raise ValueError(
            f"{label}: unsupported terms format {extension or '(none)'}; "
            "use TXT, CSV, TSV, XLSX, JSON, or YAML"
        )
    try:
        if extension == ".xlsx":
            from openpyxl import load_workbook

            workbook = load_workbook(source, read_only=True, data_only=False)
            try:
                if not workbook.worksheets:
                    raise ValueError(f"{label}: workbook has no worksheets")
                return _table_terms(
                    workbook.worksheets[0].iter_rows(values_only=True), label
                )
            finally:
                workbook.close()
        with source.open(encoding="utf-8-sig", newline="") as handle:
            if extension == ".txt":
                return _normalize_terms(
                    [line.strip() for line in handle if line.strip()], label
                )
            if extension in {".csv", ".tsv"}:
                return _table_terms(
                    csv.reader(handle, delimiter="\t" if extension == ".tsv" else ",",
                               strict=True), label
                )
            data = (json.load(handle) if extension == ".json"
                    else yaml.safe_load(handle))
            return _structured_terms(data, label)
    except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError,
            csv.Error) as exc:
        raise ValueError(f"{label}: could not read terms file: {exc}") from exc
    except ValueError:
        raise
    except Exception as exc:
        # Invalid XLSX archives and workbook formats come from several optional
        # reader exception classes; expose the same public validation interface.
        if extension == ".xlsx":
            raise ValueError(f"{label}: could not read XLSX terms file: {exc}") from exc
        raise
