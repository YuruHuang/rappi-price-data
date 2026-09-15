#!/usr/bin/env python3
"""Independently reconcile integrated workbooks to their exact published sources.

Does not import the integrated exporter or contact Rappi. Source expectations are
derived from the original tobacco workbook and published beverage audit/candidate
CSV checksums. XLSX XML is streamed so every source field can be compared twice:
once in its country partition, once in the all-country workbook.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile

try:
    from lxml import etree
    XML_ENGINE = "lxml (optional accelerator)"
except ImportError:
    from xml.etree import ElementTree as etree
    XML_ENGINE = "stdlib xml.etree.ElementTree"
from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
COUNTRIES = {"ar": "Argentina", "co": "Colombia", "pe": "Peru", "mx": "Mexico"}
KEY = ("country_code", "zone_slug", "store_id", "product_id")
GROUPS = ("Tobacco", "Water", "SSB_candidates", "Alcohol", "Comparison", "Review", "Excluded")
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
QN = "{" + NS + "}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
TOBACCO_SHARED = set("""country_code country city currency zone_slug address district latitude longitude
store_id product_id master_product_id store_type store_name parent_store_type name brand ean supplier
menu_section menu_subsection category_id price_local original_price_local availability thumbnail_url
source_term source_terms source_url scrape_timestamp""".split())
ANALYSIS_NUMERIC = set("""price_local original_price_local latitude longitude volume_per_unit_ml
pack_count total_volume_ml price_per_liter_local sugar_g_per_100ml sugar_g_per_serving serving_volume_ml
abv_pct tobacco_volume_ml tobacco_pack_count tobacco_unit_price_local tobacco_discount_pct
tobacco_discount_amount_local tobacco_nicotine_mg_per_ml tobacco_nicotine_mg_per_pouch
tobacco_nicotine_pct tobacco_puff_count source_row""".split())
DERIVED = set("""record_id source_dataset source_collection_date source_release reporting_group
candidate_view_status source_file source_row""".split())
ID_FIELDS = set("""record_id country_code zone_slug store_id product_id master_product_id source_product_id
ean category_id retail_id""".split())


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


class Audit:
    def __init__(self):
        self.errors = []
        self.error_count = 0
        self.source_hashes = {}
        self.output_hashes = {}
        self.country = {}
        self.compared_rows = 0
        self.compared_fields = 0
        self.inspected_cells = 0
        self.max_cell_length = 0
        self.support_tables = {}

    def check(self, condition, message):
        if not condition:
            self.error_count += 1
            if len(self.errors) < 100:
                self.errors.append(message)
        return bool(condition)

    def source(self, path, expected=None):
        actual = digest(path)
        if expected is not None and actual != expected:
            raise ValueError(f"Source checksum differs: {path}")
        self.source_hashes[str(Path(path).relative_to(ROOT))] = actual
        return path


def csv_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def col_index(reference):
    result = 0
    for char in reference:
        if not char.isalpha():
            break
        result = result * 26 + ord(char.upper()) - ord("A") + 1
    return result - 1


def elements(stream, tag):
    if XML_ENGINE.startswith("lxml"):
        yield from etree.iterparse(stream, events=("end",), tag=tag)
    else:
        for event, element in etree.iterparse(stream, events=("end",)):
            if element.tag == tag:
                yield event, element


def discard(element):
    element.clear()
    if hasattr(element, "getprevious"):
        while element.getprevious() is not None:
            del element.getparent()[0]


class Workbook:
    """Read cell text, numeric storage types and formulas directly from XLSX."""
    def __init__(self, path, audit):
        self.path = Path(path)
        self.audit = audit
        self.archive = ZipFile(path)
        names = self.archive.namelist()
        audit.check(not any("vbaProject" in name or name.startswith("xl/externalLinks/") for name in names),
                    f"{path}: macros or external workbook links")
        relationships = etree.fromstring(self.archive.read("xl/_rels/workbook.xml.rels"))
        relations = {item.get("Id"): item.get("Target") for item in relationships}
        workbook = etree.fromstring(self.archive.read("xl/workbook.xml"))
        self.sheets = {}
        for sheet in workbook.find(QN + "sheets"):
            audit.check(sheet.get("state", "visible") == "visible", f"{path}: hidden sheet {sheet.get('name')}")
            target = relations[sheet.get(REL)]
            self.sheets[sheet.get("name")] = target.lstrip("/") if target.startswith("/") else "xl/" + target
        self.shared = []
        if "xl/sharedStrings.xml" in names:
            with self.archive.open("xl/sharedStrings.xml") as stream:
                for _, element in elements(stream, QN + "si"):
                    self.shared.append("".join(element.itertext()))
                    discard(element)

    def rows(self, sheet):
        with self.archive.open(self.sheets[sheet]) as stream:
            for _, row in elements(stream, QN + "row"):
                cells = {}
                for cell in row:
                    if cell.tag != QN + "c":
                        continue
                    reference = cell.get("r")
                    kind = cell.get("t", "n")
                    formula = cell.find(QN + "f")
                    self.audit.check(formula is None, f"{self.path.name}/{sheet}/{reference}: formula")
                    value_element = cell.find(QN + "v")
                    if kind == "inlineStr":
                        inline = cell.find(QN + "is")
                        value = "".join(inline.itertext()) if inline is not None else None
                    elif kind == "s":
                        value = self.shared[int(value_element.text)] if value_element is not None else None
                    else:
                        value = value_element.text if value_element is not None else None
                    self.audit.inspected_cells += 1
                    if value is not None:
                        self.audit.max_cell_length = max(self.audit.max_cell_length, len(value))
                        self.audit.check(len(value.encode("utf-16-le")) // 2 <= 32767,
                                         f"{self.path.name}/{sheet}/{reference}: oversize cell")
                        self.audit.check(not ILLEGAL_XML.search(value), f"{self.path.name}/{sheet}/{reference}: invalid XML text")
                    self.audit.check(kind != "e", f"{self.path.name}/{sheet}/{reference}: Excel error cell")
                    cells[col_index(reference)] = (value, kind)
                result = [cells.get(i, (None, "n")) for i in range(max(cells, default=-1) + 1)]
                number = int(row.get("r"))
                yield number, result
                discard(row)

    def close(self):
        self.archive.close()


def load_country_sources(code, audit, tobacco_manifest, beverage_manifest):
    tobacco_entry = next(entry for entry in tobacco_manifest["files"] if entry["country_code"] == code)
    tobacco_path = audit.source(ROOT / tobacco_entry["path"], tobacco_entry["sha256"])
    book = load_workbook(tobacco_path, read_only=True, data_only=False)
    iterator = book["items"].iter_rows(values_only=True)
    tobacco_headers = next(iterator)
    tobacco = [dict(zip(tobacco_headers, row)) for row in iterator]
    location_iterator = book["locations"].iter_rows(values_only=True)
    location_headers = next(location_iterator)
    tobacco_locations = [dict(zip(location_headers, row)) for row in location_iterator]
    definition_iterator = book["data_dictionary"].iter_rows(values_only=True)
    definition_headers = next(definition_iterator)
    tobacco_definitions = [dict(zip(definition_headers, row)) for row in definition_iterator]
    book.close()
    audit.check(len(tobacco) == tobacco_entry["observations"], f"{code}: tobacco source count")
    beverage_entry = next(entry for entry in beverage_manifest["workbooks"] if entry["country_code"] == code)
    beverage_book_path = audit.source(ROOT / beverage_entry["path"], beverage_entry["sha256"])
    book = load_workbook(beverage_book_path, read_only=True, data_only=False)
    definition_iterator = book["data_dictionary"].iter_rows(values_only=True)
    definition_headers = next(definition_iterator)
    beverage_definitions = [dict(zip(definition_headers, row)) for row in definition_iterator]
    book.close()
    provenance_path = audit.source(ROOT / beverage_entry["provenance"]["path"], beverage_entry["provenance"]["sha256"])
    provenance = json.loads(provenance_path.read_text())
    audit.check(provenance.get("complete") is True, f"{code}: beverage provenance incomplete")
    specs = provenance["outputs"]
    sources = {}
    for kind in ("audit_csv", "ssb_candidates_csv", "locations_csv"):
        spec = specs[kind]
        path = audit.source(ROOT / "data/beverages" / spec["data_root_relative_path"], spec["sha256"])
        rows = csv_rows(path)
        audit.check(len(rows) == spec["rows"], f"{code}: source {kind} count")
        sources[kind] = (path, rows)
    beverage_path, beverages = sources["audit_csv"]
    candidate_keys = {tuple(row[key] for key in KEY) for row in sources["ssb_candidates_csv"][1]}
    audit.check(len(candidate_keys) == len(sources["ssb_candidates_csv"][1]), f"{code}: duplicate candidate source keys")
    return {"tobacco": tobacco, "beverages": beverages, "candidates": candidate_keys,
            "candidate_rows": {tuple(r[k] for k in KEY): r for r in sources["ssb_candidates_csv"][1]},
            "tobacco_path": tobacco_path, "beverage_path": beverage_path,
            "tobacco_release": tobacco_manifest["prepared_date"], "beverage_release": provenance["run_id"],
            "tobacco_locations": tobacco_locations, "beverage_locations": sources["locations_csv"][1],
            "definitions": {"tobacco": tobacco_definitions, "beverages": beverage_definitions},
            "provenance": provenance}


def reporting_group(dataset, row, candidates):
    if dataset == "tobacco":
        return "Tobacco"
    if tuple(row[key] for key in KEY) in candidates:
        if row["beverage_category"] not in {"review", "ssb"}:
            raise ValueError("Candidate source has an incompatible assigned category")
        return "SSB_candidates"
    return {"water": "Water", "alcohol": "Alcohol", "non_ssb": "Comparison",
            "review": "Review", "excluded": "Excluded"}[row["beverage_category"]]


def source_record_id(dataset, release, row):
    return "/".join(quote(str(value), safe="") for value in (dataset, release, *(row[key] for key in KEY)))


def mapped_field(dataset, field):
    return "tobacco_" + field if dataset == "tobacco" and field not in TOBACCO_SHARED else field


def same_value(source, actual, numeric=False):
    if source is None or source == "":
        return actual is None or actual == ""
    if actual is None or actual == "":
        return False
    if numeric:
        try:
            left, right = float(source), float(actual)
        except (ValueError, TypeError):
            return False
        return math.isfinite(left) and math.isfinite(right) and math.isclose(left, right, rel_tol=1e-13, abs_tol=1e-10)
    return str(source) == str(actual)


def expected_rows(sources, audit):
    expected, counts, dates, coverage = {}, Counter(), Counter(), {}
    fields = set(DERIVED)
    stats = {"tobacco_legacy_volume_nonblank": 0, "tobacco_legacy_pack_nonblank": 0,
             "beverage_sugar_nonblank": 0, "beverage_zero_prices": 0,
             "beverage_blank_or_zero_master_ids": 0, "source_max_text_length": 0}
    for dataset in ("tobacco", "beverages"):
        release = sources["tobacco_release" if dataset == "tobacco" else "beverage_release"]
        for index, row in enumerate(sources[dataset], 2):
            record = source_record_id(dataset, release, row)
            audit.check(record not in expected, f"Duplicate source record: {record}")
            group = reporting_group(dataset, row, sources["candidates"])
            key = tuple(str(row[k]) for k in KEY)
            date = datetime.strptime(row["scrape_timestamp"], "%Y%m%d_%H%M%S").date().isoformat()
            result = {mapped_field(dataset, field): value for field, value in row.items()}
            path = sources["tobacco_path" if dataset == "tobacco" else "beverage_path"]
            result.update(record_id=record, source_dataset=dataset, source_collection_date=date,
                          source_release=release, reporting_group=group,
                          source_file=str(path.relative_to(ROOT)), source_row=index,
                          candidate_view_status=sources["candidate_rows"].get(key, {}).get("ssb_candidate_status", "")
                          if dataset == "beverages" else "")
            fields.update(result)
            expected[record] = result
            counts[group] += 1
            dates[(dataset, date)] += 1
            if dataset == "tobacco":
                stats["tobacco_legacy_volume_nonblank"] += row.get("volume_ml") not in (None, "")
                stats["tobacco_legacy_pack_nonblank"] += row.get("pack_count") not in (None, "")
            else:
                stats["beverage_sugar_nonblank"] += bool(row["sugar_g_per_100ml"])
                stats["beverage_zero_prices"] += row["price_local"] != "" and float(row["price_local"]) == 0
                stats["beverage_blank_or_zero_master_ids"] += row["master_product_id"] in {"", "0"}
            stats["source_max_text_length"] = max(stats["source_max_text_length"],
                                                  max(len(str(value)) for value in row.values() if value is not None))
            coverage_key = (dataset, date, row["zone_slug"], group)
            if coverage_key not in coverage:
                coverage[coverage_key] = {"country_code": row["country_code"], "country": row["country"],
                    "currency": row["currency"], "source_dataset": dataset, "source_collection_date": date,
                    "zone_slug": row["zone_slug"], "reporting_group": group, "observations": 0,
                    "with_price_local": 0, "with_total_volume_ml": 0, "with_sugar_g_per_100ml": 0, "with_abv_pct": 0}
            coverage[coverage_key]["observations"] += 1
            for measure in ("price_local", "total_volume_ml", "sugar_g_per_100ml", "abv_pct"):
                coverage[coverage_key]["with_" + measure] += result.get(measure) not in (None, "")
    return expected, fields, counts, dates, list(coverage.values()), stats


def inspect_data_sheet(book, sheet, expected, expected_fields, audit, group=None):
    iterator = book.rows(sheet)
    _, first = next(iterator)
    headers = [cell[0] for cell in first]
    audit.check(len(headers) == len(set(headers)), f"{book.path.name}/{sheet}: duplicate headers")
    audit.check(set(headers) == expected_fields, f"{book.path.name}/{sheet}: source/derived field set differs")
    seen = set()
    for number, cells in iterator:
        cells += [(None, "n")] * (len(headers) - len(cells))
        values = {key: value for key, (value, kind) in zip(headers, cells)}
        record = values.get("record_id")
        if not audit.check(record in expected, f"{book.path.name}/{sheet}/{number}: unexpected record {record}"):
            continue
        audit.check(record not in seen, f"{book.path.name}/{sheet}/{number}: duplicate record {record}")
        seen.add(record)
        original = expected[record]
        if group:
            audit.check(original["reporting_group"] == group, f"{book.path.name}/{sheet}/{number}: incorrect partition")
        for field, (value, kind) in zip(headers, cells):
            source = original.get(field)
            audit.compared_fields += 1
            audit.check(same_value(source, value, field in ANALYSIS_NUMERIC),
                        f"{book.path.name}/{sheet}/{number}/{field}: source value changed")
            if value is not None and value != "":
                if field in ANALYSIS_NUMERIC:
                    audit.check(kind == "n", f"{book.path.name}/{sheet}/{number}/{field}: numeric field is {kind}")
                elif field in ID_FIELDS or isinstance(source, str):
                    audit.check(kind in {"inlineStr", "s", "str"},
                                f"{book.path.name}/{sheet}/{number}/{field}: text/ID stored as {kind}")
        audit.compared_rows += 1
    required = {key for key, row in expected.items() if group is None or row["reporting_group"] == group}
    audit.check(seen == required, f"{book.path.name}/{sheet}: missing/extra records ({len(required-seen)} missing)")
    return seen, headers


def table(book, sheet):
    iterator = book.rows(sheet)
    _, first = next(iterator)
    headers = [value for value, kind in first]
    result = []
    for _, cells in iterator:
        cells += [(None, "n")] * (len(headers) - len(cells))
        result.append({key: value for key, (value, kind) in zip(headers, cells)})
    return result


def compare_table(actual, expected, keys, audit, label, numeric=()):
    actual_map = {tuple(row.get(k) or "" for k in keys): row for row in actual}
    expected_map = {tuple(str(row.get(k) or "") for k in keys): row for row in expected}
    audit.check(len(actual_map) == len(actual), f"{label}: duplicate rows")
    audit.check(set(actual_map) == set(expected_map), f"{label}: missing/extra rows")
    for key in actual_map.keys() & expected_map.keys():
        left, right = expected_map[key], actual_map[key]
        for field, source in left.items():
            audit.check(same_value(source, right.get(field), field in numeric), f"{label}/{key}/{field}: changed summary")


def expected_locations(sources):
    rows = []
    code = sources["tobacco"][0]["country_code"]
    for dataset, key in (("tobacco", "tobacco_locations"), ("beverages", "beverage_locations")):
        for row in sources[key]:
            rows.append({"source_dataset": dataset, "country_code": code,
                         "country": sources["tobacco"][0]["country"], "currency": sources["tobacco"][0]["currency"],
                         "zone_slug": row.get("zone_slug", row.get("slug")), "address": row["address"],
                         "district": row["district"], "latitude": row.get("latitude", row.get("lat")),
                         "longitude": row.get("longitude", row.get("lng"))})
    return rows


def inspect_support(book, sources, coverage, locations, manifest, audit, code=None):
    label = book.path.name
    actual_coverage = table(book, "Coverage")
    compare_table(actual_coverage, coverage,
                  ("country_code", "source_dataset", "source_collection_date", "zone_slug", "reporting_group"),
                  audit, label + "/Coverage", numeric=("observations", "with_price_local", "with_total_volume_ml",
                                                       "with_sugar_g_per_100ml", "with_abv_pct"))
    actual_locations = table(book, "Locations")
    compare_table(actual_locations, locations, ("country_code", "source_dataset", "zone_slug"),
                  audit, label + "/Locations", numeric=("latitude", "longitude"))
    source_entries = [entry for entry in manifest["sources"] if code is None or not entry["country_code"] or entry["country_code"] == code]
    actual_sources = table(book, "Sources")
    compare_table(actual_sources, source_entries, ("path",), audit, label + "/Sources", numeric=("bytes", "rows"))
    notes = table(book, "Read_me")
    note_map = {row["topic"]: row["note"] for row in notes}
    count = sum(row["observations"] for row in coverage)
    audit.check(f"{count:,} source observations" in note_map.get("Contents", ""), label + ": summary total")
    audit.check(all(date in note_map.get("Collection dates", "") for date in ("2026-08-16", "2026-09-10")),
                label + ": collection dates absent or incorrect")
    dictionary = table(book, "Dictionary")
    mapped = {(row["source_dataset"], row["source_column"]): row for row in dictionary if row["source_dataset"] != "integration"}
    for source in sources:
        for dataset in ("tobacco", "beverages"):
            definitions = {row["column"]: row["definition"] for row in source["definitions"][dataset]
                           if dataset != "tobacco" or row.get("sheet") == "items"}
            for field in source[dataset][0]:
                audit.check((dataset, field) in mapped, f"{label}: undefined source field {dataset}/{field}")
                if (dataset, field) in mapped:
                    audit.check(mapped[(dataset, field)]["column"] == mapped_field(dataset, field),
                                f"{label}: incorrect dictionary mapping {dataset}/{field}")
                if field in definitions:
                    audit.check(any(row.get("source_dataset") == dataset and row.get("source_column") == field
                                    and row.get("definition") == definitions[field] for row in dictionary),
                                f"{label}: source dictionary definition changed {dataset}/{field}")
    actual_counts = {"Read_me": len(notes), "Coverage": len(actual_coverage), "Locations": len(actual_locations),
                     "Sources": len(actual_sources), "Dictionary": len(dictionary)}
    audit.support_tables[label] = actual_counts
    return actual_counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "datasets/integrated")
    parser.add_argument("--report", type=Path, default=ROOT / "data/validation/integrated_release_audit.json")
    args = parser.parse_args()
    audit = Audit()
    manifest_path = args.input_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    initial_manifest_hash = digest(manifest_path)
    tobacco_manifest = json.loads(audit.source(ROOT / "datasets/manifest.json").read_text())
    beverage_manifest = json.loads(audit.source(ROOT / "datasets/beverages/manifest.json").read_text())
    output_entries = {entry["path"]: entry for entry in manifest["files"]}
    audit.check(set(output_entries) == {"all_countries.xlsx", "overflow_cells.csv", *[name.lower()+".xlsx" for name in COUNTRIES.values()]},
                "Output file set differs from five workbooks plus overflow sidecar")
    audit.check(len(output_entries) == len(manifest["files"]), "Duplicate output manifest paths")
    for name, entry in output_entries.items():
        path = args.input_dir / name
        actual = digest(path)
        audit.output_hashes[name] = actual
        audit.check(actual == entry["sha256"] and path.stat().st_size == entry["bytes"], f"Output checksum/size differs: {name}")
    audit.check(manifest["observation_key"] == ["source_dataset", "source_release", *KEY], "Integrated observation key differs")
    audit.check(manifest["network_requests"] == 0, "Manifest unexpectedly reports new collection")
    audit.check(manifest["collection_waves"] == {"tobacco": ["2026-08-16"], "beverages": ["2026-09-10"]}, "Collection-wave metadata differs")
    audit.check(digest(ROOT / manifest["exporter"]) == manifest["exporter_sha256"], "Exporter checksum differs")
    overflow = csv_rows(args.input_dir / "overflow_cells.csv")
    audit.check(not overflow and manifest["overflow_cells"] == 0, "Unexpected overflow/truncated source text")
    master = Workbook(args.input_dir / "all_countries.xlsx", audit)
    audit.check(set(master.sheets) == {"Read_me", *COUNTRIES.values(), "Coverage", "Locations", "Dictionary", "Sources"}, "Master sheets differ")
    all_coverage, all_locations, retained_sources = [], [], []
    total_groups, source_dates, all_fields = Counter(), Counter(), None
    for code, name in COUNTRIES.items():
        print(f"Auditing {name} against exact sources...", flush=True)
        sources = load_country_sources(code, audit, tobacco_manifest, beverage_manifest)
        expected, fields, counts, dates, coverage, stats = expected_rows(sources, audit)
        if all_fields is None:
            all_fields = fields
        audit.check(fields == all_fields, f"{code}: source schemas unexpectedly differ")
        country = Workbook(args.input_dir / (name.lower()+".xlsx"), audit)
        audit.check(set(country.sheets) == {"Read_me", *GROUPS, "Locations", "Dictionary", "Sources", "Coverage"}, f"{code}: country sheets differ")
        seen = set()
        for group in GROUPS:
            found, headers = inspect_data_sheet(country, group, expected, fields, audit, group)
            audit.check(not seen.intersection(found), f"{code}: overlapping reporting tabs")
            seen.update(found)
            audit.check(headers == manifest["columns"], f"{code}/{group}: header and manifest disagree")
        audit.check(seen == set(expected), f"{code}: union of reporting tabs loses source rows")
        found, headers = inspect_data_sheet(master, name, expected, fields, audit)
        audit.check(headers == manifest["columns"], f"Master/{name}: header and manifest disagree")
        locations = expected_locations(sources)
        support = inspect_support(country, [sources], coverage, locations, manifest, audit, code)
        entry = output_entries[name.lower()+".xlsx"]
        audit.check(entry["observations"] == len(expected), f"{code}: manifest observation count")
        audit.check(entry["reporting_groups"] == dict(counts), f"{code}: manifest group counts")
        audit.check(entry["sheet_rows"] == {**dict(counts), **support}, f"{code}: manifest sheet row counts")
        country.close()
        source_keys = {dataset: {tuple(str(row[k]) for k in KEY) for row in sources[dataset]}
                       for dataset in ("tobacco", "beverages")}
        audit.country[code] = {"observations": len(expected), "source_rows": {dataset: len(sources[dataset]) for dataset in ("tobacco", "beverages")},
            "reporting_groups": dict(counts), "collection_dates": {f"{dataset}/{date}": value for (dataset, date), value in dates.items()},
            "cross_wave_repeated_four_keys": len(source_keys["tobacco"] & source_keys["beverages"]), **stats}
        total_groups.update(counts)
        source_dates.update(dates)
        all_coverage.extend(coverage)
        all_locations.extend(locations)
        retained_sources.append({**sources, "tobacco": sources["tobacco"][:1], "beverages": sources["beverages"][:1],
                                 "candidate_rows": {}, "candidates": set()})
        del expected, sources
    support = inspect_support(master, retained_sources, all_coverage, all_locations, manifest, audit)
    master.close()
    expected_master_counts = {**{COUNTRIES[code]: values["observations"] for code, values in audit.country.items()}, **support}
    audit.check(output_entries["all_countries.xlsx"]["sheet_rows"] == expected_master_counts, "Master manifest sheet counts differ")
    total = sum(total_groups.values())
    audit.check(total == 95688 and manifest["observations"] == total, "Integrated overall total differs")
    recorded_sources = {entry["path"]: entry for entry in manifest["sources"]}
    audit.check(len(recorded_sources) == len(manifest["sources"]), "Duplicate source manifest paths")
    audit.check(set(recorded_sources) == set(audit.source_hashes), "Source manifest missing/extra inputs")
    for name, value in audit.source_hashes.items():
        audit.check(digest(ROOT / name) == value, f"Source changed during independent audit: {name}")
        entry = recorded_sources.get(name, {})
        audit.check(entry.get("sha256") == value and entry.get("bytes") == (ROOT/name).stat().st_size,
                    f"Recorded input checksum/size differs: {name}")
    for name, value in audit.output_hashes.items():
        audit.check(digest(args.input_dir/name) == value, f"Output changed during independent audit: {name}")
    audit.check(digest(manifest_path) == initial_manifest_hash, "Integrated manifest changed during audit")
    report = {"schema_version": 1, "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if audit.error_count == 0 else "failed", "errors_count": audit.error_count, "errors": audit.errors,
        "method": "Independent exact-source reconciliation using original tobacco items and published beverage audit/candidate CSVs; no exporter imports or new collection",
        "xml_parser": XML_ENGINE,
        "observations": total, "country": audit.country, "reporting_groups": dict(total_groups),
        "compared_workbook_rows": audit.compared_rows, "compared_fields": audit.compared_fields,
        "inspected_cells": audit.inspected_cells, "max_output_cell_characters": audit.max_cell_length,
        "source_sha256": audit.source_hashes, "output_sha256": audit.output_hashes,
        "integrated_manifest_sha256": initial_manifest_hash, "auditor_sha256": digest(Path(__file__)),
        "checks": ["Every source field, identity, date and source-row pointer reconciled in country and master outputs",
            "Exact disjoint category partitions and separately published SSB candidate membership",
            "All coverage/summary/location/source-table counts and values",
            "ID/source text types, numeric analysis fields, explicit zero versus missing",
            "No formulas, Excel errors, hidden sheets, macros, external workbook links, oversized cells or unexpected overflow",
            "Exact input/output hashes, source manifests and unchanged files during audit"],
        "limitations": ["Checks establish source preservation and accounting, not correctness of retailer metadata or original classifications",
            "Tobacco includes previously selected published items; beverage sources include all audit observations",
            "Separate August16 and September10 collection waves; not a simultaneous cross-category market sample",
            "No new product-detail capture, catalog-completeness validation or source-origin authentication"]}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "observations": total, "compared_rows": audit.compared_rows,
                      "errors_count": audit.error_count, "first_errors": audit.errors[:10], "report": str(args.report)}, indent=2))
    return 0 if audit.error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
