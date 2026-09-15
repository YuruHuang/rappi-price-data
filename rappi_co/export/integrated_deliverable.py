"""Offline, source-preserving integration of the two frozen study releases.

Run ``python -m rappi_co.export.integrated_deliverable --out NEW_DIRECTORY``.
The destination must not exist. No collection or reclassification is performed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


COUNTRIES = {"ar": ("Argentina", "ARS"), "co": ("Colombia", "COP"),
             "pe": ("Peru", "PEN"), "mx": ("Mexico", "MXN")}
KEY = ("country_code", "zone_slug", "store_id", "product_id")
GROUPS = ("Tobacco", "Water", "SSB_candidates", "Alcohol", "Comparison", "Review", "Excluded")
COMMON = set("country_code country city currency zone_slug address district latitude longitude "
             "store_id product_id master_product_id store_type store_name parent_store_type "
             "name brand ean supplier menu_section menu_subsection category_id price_local "
             "original_price_local availability thumbnail_url source_term source_terms source_url "
             "scrape_timestamp".split())
LEADING = """name reporting_group brand price_local currency source_collection_date
volume_per_unit_ml pack_count total_volume_ml price_per_liter_local sugar_g_per_100ml abv_pct
beverage_category beverage_subcategory sugar_status candidate_view_status beverage_flags
source_dataset source_release country_code country zone_slug store_name store_id product_id master_product_id
original_price_local sugar_g_per_serving serving_volume_ml
tobacco_study_category tobacco_product_type tobacco_volume_ml tobacco_pack_count
tobacco_unit_price_local tobacco_unit_price_unit tobacco_nicotine_mg_per_ml
tobacco_nicotine_mg_per_pouch tobacco_nicotine_pct store_type city address
district latitude longitude ean availability scrape_timestamp record_id source_file source_row""".split()
NUMERIC = set("""price_local original_price_local latitude longitude volume_per_unit_ml
pack_count total_volume_ml price_per_liter_local sugar_g_per_100ml sugar_g_per_serving
serving_volume_ml abv_pct tobacco_volume_ml tobacco_pack_count tobacco_unit_price_local
tobacco_discount_pct tobacco_discount_amount_local tobacco_nicotine_mg_per_ml
tobacco_nicotine_mg_per_pouch tobacco_nicotine_pct tobacco_puff_count source_row""".split())
DERIVED = {
    "record_id": "Source dataset/release plus percent-encoded country/location/store/product key; separate releases and datasets cannot collide.",
    "source_dataset": "tobacco or beverages; identifies the frozen source release.",
    "source_collection_date": "Calendar date parsed from the original scrape_timestamp, in its recorded time basis; not the preparation date.",
    "source_release": "Tobacco manifest prepared_date or beverage provenance run_id.",
    "reporting_group": "Disjoint presentation tab. Exact published SSB candidate membership takes precedence over the source review category; original classifications are retained.",
    "candidate_view_status": "ssb_candidate_status from the published SSB candidate CSV, joined by the exact four-part observation key. Original audit ssb_candidate_status is retained separately.",
    "source_file": "Repository-relative source items workbook or exact beverage audit CSV.",
    "source_row": "One-based physical CSV record/worksheet row, with header at row 1.",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _csv(path: Path):
    csv.field_size_limit(100_000_000)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        names = reader.fieldnames or []
        if not names or len(names) != len(set(names)):
            raise ValueError(f"Missing/duplicate CSV headers: {path}")
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"Malformed CSV record: {path}")
            yield row


def _sheet(workbook, name: str):
    rows = workbook[name].iter_rows(values_only=False)
    header = [cell.value for cell in next(rows)]
    if not all(isinstance(k, str) for k in header) or len(set(header)) != len(header):
        raise ValueError(f"Invalid worksheet headers: {name}")
    for cells in rows:
        if any(cell.data_type == "f" for cell in cells):
            raise ValueError(f"Formula in frozen source worksheet: {name}")
        yield {k: cell.value for k, cell in zip(header, cells)}


def source_column(dataset: str, column: str) -> str:
    return "tobacco_" + column if dataset == "tobacco" and column not in COMMON else column


def _text(value) -> str:
    return "" if value is None else str(value)


def observation_key(row: dict) -> tuple[str, ...]:
    values = tuple(_text(row.get(k)) for k in KEY)
    if not all(values):
        raise ValueError(f"Missing observation identity: {values}")
    # IDs must already be text; converting Excel numeric IDs can conceal precision loss.
    if any(not isinstance(row.get(k), str) for k in KEY):
        raise ValueError(f"Source identity was not stored as text: {values}")
    for column in ("ean", "master_product_id", "source_product_id", "category_id"):
        if row.get(column) not in (None, "") and not isinstance(row[column], str):
            raise ValueError(f"Source {column} was not stored as text: {values}")
    return values


def collection_date(timestamp: str) -> str:
    try:
        return datetime.strptime(timestamp, "%Y%m%d_%H%M%S").date().isoformat()
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Unsupported source collection timestamp: {timestamp!r}") from exc


def reporting_group(row: dict, candidates: dict) -> str:
    key = observation_key(row)
    category = row.get("beverage_category")
    if key in candidates:
        if category not in {"review", "ssb"}:
            raise ValueError(f"Candidate overlaps incompatible category {category}: {key}")
        return "SSB_candidates"
    mapping = {"water": "Water", "alcohol": "Alcohol", "non_ssb": "Comparison",
               "review": "Review", "excluded": "Excluded"}
    if category not in mapping:
        raise ValueError(f"Unmapped beverage category: {category!r} for {key}")
    return mapping[category]


def _number(value, column: str):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError(f"Boolean in numeric field {column}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric field {column}: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"Nonfinite numeric field {column}: {value!r}")
    return number


def canonical_row(row: dict, dataset: str, release: str, path: str, source_row: int,
                  candidates: dict) -> dict:
    key = observation_key(row)
    result = {source_column(dataset, k): (_number(v, source_column(dataset, k))
              if source_column(dataset, k) in NUMERIC else v) for k, v in row.items()}
    result.update(record_id="/".join(quote(v, safe="") for v in (dataset, release, *key)),
                  source_dataset=dataset, source_collection_date=collection_date(row["scrape_timestamp"]),
                  source_release=release, reporting_group="Tobacco" if dataset == "tobacco"
                  else reporting_group(row, candidates), source_file=path, source_row=source_row,
                  candidate_view_status=candidates.get(key, {}).get("ssb_candidate_status", ""))
    return result


@dataclass
class Country:
    code: str
    tobacco: list[dict]
    tobacco_path: str
    tobacco_release: str
    audit_path: Path
    audit_relative: str
    beverage_release: str
    candidates: dict
    source_headers: dict
    locations: list[dict]
    definitions: dict
    coverage: list[dict] = field(default_factory=list)

    def rows(self):
        for index, row in enumerate(self.tobacco, 2):
            yield canonical_row(row, "tobacco", self.tobacco_release, self.tobacco_path, index, {})
        for index, row in enumerate(_csv(self.audit_path), 2):
            yield canonical_row(row, "beverages", self.beverage_release,
                                self.audit_relative, index, self.candidates)


class Inputs:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.records = {}

    def add(self, relative: str, role: str, country="", expected=None) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"Input escapes repository: {relative}")
        digest = sha256(path)
        size = path.stat().st_size
        if expected and (digest != expected["sha256"] or size != expected["bytes"]):
            raise ValueError(f"Source hash/size mismatch: {relative}")
        entry = {"path": relative, "role": role, "country_code": country,
                 "bytes": size, "sha256": digest}
        if expected and "rows" in expected:
            entry["rows"] = expected["rows"]
        self.records[relative] = entry
        return path

    def assert_unchanged(self):
        for relative, record in self.records.items():
            path = self.root / relative
            if path.stat().st_size != record["bytes"] or sha256(path) != record["sha256"]:
                raise ValueError(f"Source changed during export: {relative}")


def _definitions(workbook, dataset):
    result = {}
    for row in _sheet(workbook, "data_dictionary"):
        if dataset == "tobacco" and row.get("sheet") != "items":
            continue
        result[row["column"]] = row["definition"]
    return result


def _check_location(row, locations, code):
    name, currency = COUNTRIES[code]
    if (row.get("country_code"), row.get("country"), row.get("currency")) != (code, name, currency):
        raise ValueError(f"Country/currency mismatch: {observation_key(row)}")
    zone = row.get("zone_slug")
    if zone not in locations:
        raise ValueError(f"Unknown source location: {zone}")
    location = locations[zone]
    for column in ("address", "district", "latitude", "longitude"):
        a, b = row.get(column), location.get(column)
        equal = _number(a, column) == _number(b, column) if column in {"latitude", "longitude"} else a == b
        if not equal:
            raise ValueError(f"Location {column} mismatch: {observation_key(row)}")


def prepare(root: Path) -> tuple[Inputs, list[Country], list[str]]:
    inputs = Inputs(root)
    tm = json.loads(inputs.add("datasets/manifest.json", "tobacco_release_manifest").read_text())
    bm = json.loads(inputs.add("datasets/beverages/manifest.json", "beverage_release_manifest").read_text())
    tobacco_entries = {x["country_code"]: x for x in tm["files"]}
    beverage_entries = {x["country_code"]: x for x in bm["workbooks"]}
    if set(tobacco_entries) != set(COUNTRIES) or set(beverage_entries) != set(COUNTRIES):
        raise ValueError("Both releases must contain each of the four countries exactly once")
    if len(tm["files"]) != 4 or len(bm["workbooks"]) != 4:
        raise ValueError("Duplicate country in source manifests")
    countries = []
    columns = list(LEADING)
    for code in COUNTRIES:
        te, be = tobacco_entries[code], beverage_entries[code]
        tp = inputs.add(te["path"], "tobacco_items_and_dictionary", code, te)
        tw = load_workbook(tp, read_only=True, data_only=False)
        try:
            tobacco = list(_sheet(tw, "items"))
            tl = list(_sheet(tw, "locations"))
            td = _definitions(tw, "tobacco")
        finally:
            tw.close()
        bp = inputs.add(be["path"], "beverage_dictionary", code, be)
        bw = load_workbook(bp, read_only=True, data_only=False)
        try:
            bd = _definitions(bw, "beverages")
        finally:
            bw.close()
        pp = inputs.add(be["provenance"]["path"], "beverage_provenance", code, be["provenance"])
        prov = json.loads(pp.read_text())
        if not prov.get("complete") or prov["plan"]["country_code"] != code:
            raise ValueError(f"Incomplete/wrong-country beverage provenance: {code}")
        paths = {}
        for kind in ("audit_csv", "ssb_candidates_csv", "locations_csv"):
            entry = prov["outputs"][kind]
            relative = "data/beverages/" + entry["data_root_relative_path"]
            paths[kind] = inputs.add(relative, kind, code, entry)
        candidate_rows = list(_csv(paths["ssb_candidates_csv"]))
        candidates = {observation_key(r): r for r in candidate_rows}
        if len(candidates) != len(candidate_rows):
            raise ValueError(f"Duplicate SSB candidate keys: {code}")
        bl = list(_csv(paths["locations_csv"]))
        for kind, count in (("ssb_candidates_csv", len(candidates)), ("locations_csv", len(bl))):
            if count != prov["outputs"][kind]["rows"]:
                raise ValueError(f"Source row-count mismatch: {code}/{kind}")
        if len(tobacco) != te["observations"] or len(candidates) != be["ssb_candidate_observations"]:
            raise ValueError(f"Manifest observation count mismatch: {code}")
        if len(bl) != be["locations"]:
            raise ValueError(f"Manifest location count mismatch: {code}")
        tobacco_locations = {r["zone_slug"]: r for r in tl}
        beverage_locations = {r["slug"]: {"zone_slug": r["slug"], "address": r["address"],
                              "district": r["district"], "latitude": r["lat"], "longitude": r["lng"]}
                              for r in bl}
        if len(tobacco_locations) != len(tl) or len(beverage_locations) != len(bl):
            raise ValueError(f"Duplicate locations: {code}")
        if set(beverage_locations) != {r["slug"] for r in prov["plan"]["addresses"]}:
            raise ValueError(f"Provenance location mismatch: {code}")
        locations = []
        for dataset, locs in (("tobacco", tobacco_locations), ("beverages", beverage_locations)):
            for zone, location in locs.items():
                locations.append({"source_dataset": dataset, "country_code": code,
                                  "country": COUNTRIES[code][0], "currency": COUNTRIES[code][1],
                                  **{k: location[k] for k in ("zone_slug", "address", "district", "latitude", "longitude")}})
        country = Country(code, tobacco, te["path"], tm["prepared_date"], paths["audit_csv"],
                          str(paths["audit_csv"].relative_to(inputs.root)), prov["run_id"], candidates,
                          {}, locations, {"tobacco": (te["path"], td), "beverages": (be["path"], bd)})
        groups, categories, observed_candidates = Counter(), Counter(), set()
        coverage = {}
        for dataset, source_rows, locs in (("tobacco", tobacco, tobacco_locations),
                                           ("beverages", _csv(paths["audit_csv"]), beverage_locations)):
            seen = set()
            for row_number, row in enumerate(source_rows, 2):
                key = observation_key(row)
                if key in seen:
                    raise ValueError(f"Duplicate observation: {dataset}/{key}")
                seen.add(key)
                _check_location(row, locs, code)
                date = collection_date(row["scrape_timestamp"])
                if dataset == "tobacco" and date != tm["source_collection_date"]:
                    raise ValueError(f"Tobacco collection-date mismatch: {key}")
                if dataset == "beverages":
                    categories[row["beverage_category"]] += 1
                    if key in candidates:
                        candidate = candidates[key]
                        for column, value in candidate.items():
                            if column != "ssb_candidate_status" and row.get(column) != value:
                                raise ValueError(f"Candidate/audit source mismatch: {key}/{column}")
                        observed_candidates.add(key)
                canonical = canonical_row(row, dataset, country.tobacco_release if dataset == "tobacco"
                                          else country.beverage_release, "", row_number, candidates if dataset == "beverages" else {})
                country.source_headers.setdefault(dataset, list(row))
                for column in canonical:
                    if column not in columns:
                        columns.append(column)
                group = canonical["reporting_group"]
                groups[group] += 1
                ck = dataset, date, row["zone_slug"], group
                if ck not in coverage:
                    coverage[ck] = {"country_code": code, "country": COUNTRIES[code][0], "currency": COUNTRIES[code][1],
                                    "source_dataset": dataset, "source_collection_date": date,
                                    "zone_slug": row["zone_slug"], "reporting_group": group, "observations": 0,
                                    "with_price_local": 0, "with_total_volume_ml": 0,
                                    "with_sugar_g_per_100ml": 0, "with_abv_pct": 0}
                c = coverage[ck]
                c["observations"] += 1
                for measure in ("price_local", "total_volume_ml", "sugar_g_per_100ml", "abv_pct"):
                    c["with_" + measure] += canonical.get(measure) not in (None, "")
            expected = te["observations"] if dataset == "tobacco" else be["raw_observations"]
            if len(seen) != expected:
                raise ValueError(f"Source observation count mismatch: {dataset}/{code}")
            if dataset == "beverages" and len(seen) != prov["outputs"]["audit_csv"]["rows"]:
                raise ValueError(f"Provenance audit row-count mismatch: {code}")
        if observed_candidates != set(candidates):
            raise ValueError(f"Candidates absent from audit: {code}")
        for category, metric in (("water", "water_observations"), ("alcohol", "alcohol_observations"),
                                  ("review", "review_observations"), ("non_ssb", "comparison_observations"),
                                  ("excluded", "excluded_observations"), ("ssb", "confirmed_ssb_observations")):
            if categories[category] != be[metric]:
                raise ValueError(f"Beverage category count mismatch: {code}/{category}")
        if sum(groups.values()) != te["observations"] + be["raw_observations"]:
            raise ValueError(f"Row conservation failure: {code}")
        country.coverage = list(coverage.values())
        countries.append(country)
    inputs.assert_unchanged()
    return inputs, countries, columns


def _hidden(column):
    return column not in LEADING and (column.endswith(("_json", "_evidence", "_path", "_paths"))
                                     or column in {"source_terms", "product_information", "nutrition_text", "ingredients_text"})


class Overflow:
    def __init__(self, path):
        self.handle = path.open("w", encoding="utf-8", newline="")
        self.writer = csv.DictWriter(self.handle, fieldnames=["overflow_id", "record_id", "column",
                                                            "reason", "characters", "sha256", "full_text"])
        self.writer.writeheader()
        self.count = 0

    def value(self, value, record_id, column):
        if not isinstance(value, str):
            return value
        # UTF-16 units match Excel's string bound, including non-BMP characters.
        if len(value.encode("utf-16-le")) // 2 <= 32767 and not ILLEGAL_CHARACTERS_RE.search(value):
            return value
        self.count += 1
        oid = f"overflow_{self.count:06d}"
        reason = "excel_text_limit" if len(value.encode("utf-16-le")) // 2 > 32767 else "invalid_xml_control"
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        self.writer.writerow(dict(overflow_id=oid, record_id=record_id, column=column,
                                  reason=reason, characters=len(value), sha256=digest, full_text=value))
        return f"[Full text: overflow_cells.csv#{oid}; sha256={digest}]"

    def close(self):
        self.handle.close()


class Excel:
    def __init__(self, path: Path, sheets: list[str]):
        self.path = path
        self.workbook = Workbook(write_only=True)
        self.workbook.properties.creator = "Rappi study offline integration"
        self.sheets = {name: self.workbook.create_sheet(name) for name in sheets}
        self.columns = {}
        self.counts = Counter()
        self.header_font = Font(bold=True, color="FFFFFF")
        self.header_fill = PatternFill("solid", fgColor="17365D")
        self.stripe = PatternFill("solid", fgColor="EFF4FA")

    def table(self, name, columns, records=None):
        ws = self.sheets[name]
        self.columns[name] = list(columns)
        ws.freeze_panes = "C2" if "record_id" in columns else "A2"
        ws.sheet_view.showGridLines = False
        ws.sheet_view.zoomScale = 85
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_options.horizontalCentered = False
        ws.row_dimensions[1].height = 34
        for index, column in enumerate(columns, 1):
            width = 44 if column in {"name", "definition", "note", "value"} else 23
            if column in NUMERIC:
                width = 18
            if column in {"currency", "country_code"}:
                width = 11
            if column == "note":
                width = 110
            if column == "definition":
                width = 80
            if column in {"record_id", "source_file", "path", "sha256", "source_row"}:
                width = 30 if column != "source_row" else 12
            dimension = ws.column_dimensions[get_column_letter(index)]
            dimension.width = width
            dimension.hidden = _hidden(column)
        header = []
        for column in columns:
            cell = WriteOnlyCell(ws, column)
            cell.font, cell.fill = self.header_font, self.header_fill
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            cell.data_type = "s"
            header.append(cell)
        ws.append(header)
        if records is not None:
            for row in records:
                self.append(name, row)

    def append(self, name, row):
        ws = self.sheets[name]
        cells = []
        stripe = self.counts[name] % 2 == 1
        for column in self.columns[name]:
            value = row.get(column)
            if value is None or value == "":
                cells.append(None)
                continue
            if isinstance(value, str) and (len(value.encode("utf-16-le")) // 2 > 32767 or ILLEGAL_CHARACTERS_RE.search(value)):
                raise ValueError(f"Unprocessed unsafe Excel text: {name}/{column}")
            cell = WriteOnlyCell(ws, value)
            if isinstance(value, str):
                cell.data_type = "s"  # literal =,+,-,@ and error-looking strings stay text
                cell.number_format = "@"
                if column in {"note", "definition"}:
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
            elif column in NUMERIC or isinstance(value, (float, int)):
                cell.number_format = "0.########"
            if stripe:
                cell.fill = self.stripe
            cells.append(cell)
        wrapped = [row.get(k) for k in ("note", "definition") if isinstance(row.get(k), str)]
        if wrapped:
            width = 105 if "note" in row else 75
            ws.row_dimensions[self.counts[name] + 2].height = min(180, max(30, 15 * (max(len(v) for v in wrapped) // width + 2)))
        ws.append(cells)
        self.counts[name] += 1

    def save(self):
        for name, ws in self.sheets.items():
            ws.auto_filter.ref = f"A1:{get_column_letter(len(self.columns[name]))}{self.counts[name] + 1}"
        self.workbook.save(self.path)
        with zipfile.ZipFile(self.path) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"Corrupt output workbook: {self.path}")
        return {"path": self.path.name, "bytes": self.path.stat().st_size,
                "sha256": sha256(self.path), "sheet_rows": dict(self.counts)}


def _dictionary(countries, columns):
    result = [{"column": k, "source_dataset": "integration", "source_column": "",
               "definition": v, "definition_source": "integrated exporter schema", "excel_type": "numeric" if k in NUMERIC else "text",
               "hidden_by_default": _hidden(k)} for k, v in DERIVED.items()]
    seen = set()
    for country in countries:
        for dataset, headers in country.source_headers.items():
            path, definitions = country.definitions[dataset]
            for original in headers:
                column = source_column(dataset, original)
                definition = definitions.get(original, "Retained source field; no definition supplied in the frozen workbook dictionary.")
                key = column, dataset, definition
                if key in seen:
                    continue
                seen.add(key)
                result.append({"column": column, "source_dataset": dataset, "source_column": original,
                               "definition": definition, "definition_source": path + "#data_dictionary",
                               "excel_type": "numeric; missing remains blank" if column in NUMERIC else "original value; text remains literal text",
                               "hidden_by_default": _hidden(column)})
    return sorted(result, key=lambda r: columns.index(r["column"]))


def _metadata(excel, countries, columns, sources, overflow_count):
    count = sum(sum(r["observations"] for r in c.coverage) for c in countries)
    waves = {dataset: sorted({r["source_collection_date"] for c in countries for r in c.coverage
                              if r["source_dataset"] == dataset}) for dataset in ("tobacco", "beverages")}
    readme = [
        ("Contents", f"{count:,} source observations: the published tobacco target rows and the complete beverage audit, including review/comparison/exclusions. These are not all confirmed target products. Country files and the master are alternative presentations of the same observations; never append them together."),
        ("Collection dates", f"Tobacco: {', '.join(waves['tobacco'])}. Beverages: {', '.join(waves['beverages'])}. Separate collection waves; preparation/export date is not collection date. Original scrape_timestamp is retained; timezone was not stated by those timestamp strings."),
        ("Observation identity", "source_dataset + source_release + country_code + zone_slug + store_id + product_id. Store/location observations are not unique national products. Cross-source sightings remain separate."),
        ("SSB candidates", "Exact released candidate CSV membership. Sweetening and quantitative sugar are unconfirmed where blank. Candidates are removed from the Review presentation tab; original beverage_category, ssb_candidate_status and flags remain unchanged. candidate_view_status preserves the separate candidate CSV status."),
        ("Review and exclusions", "Review contains remaining unresolved beverage observations. Comparison retains non-SSB comparators. Excluded retains every source exclusion; none is silently discarded."),
        ("Measurements", "Prices are numeric and remain in each country's currency; there is no currency conversion or same-wave price comparison. Missing measurements stay blank, not zero. No values are inferred from brands or typical sizes."),
        ("Separate quantities", "Unshared tobacco fields are prefixed tobacco_. Tobacco volume/pack/unit-price semantics are retained from that release and are not beverage liters. Beverage volume_ml is a legacy source field; use volume_per_unit_ml and total_volume_ml with their evidence for beverage analysis."),
        ("Source preservation", "All item/audit columns are retained. Numeric analysis fields are stored as Excel numbers; IDs and source strings remain literal text. source_file/source_row identify the exact original record."),
        ("Evidence columns", "Long source/evidence columns may be hidden for readability. In Excel, select columns, right-click and Unhide to view them. Dictionary marks hidden columns."),
        ("Overflow evidence", f"{overflow_count} cells use explicit references to overflow_cells.csv, which preserves full text and SHA-256 if Excel's text/XML limits prevent inline storage. This sidecar is part of the deliverable; no silent truncation."),
        ("Coverage limits", "Finite search protocol at two locations per country; national/platform catalog completeness is unknown. Sugar concentration is absent in the frozen beverage release. No new collection or product-detail enrichment occurs in this export."),
        ("Sources", "Sources records input hashes. manifest.json records all output hashes, partition counts and source releases. Frozen source workbooks and manifests are not modified."),
    ]
    excel.table("Read_me", ["topic", "note"], ({"topic": k, "note": v} for k, v in readme))
    coverage = [r for c in countries for r in c.coverage]
    excel.table("Coverage", list(coverage[0]), coverage)
    locations = [r for c in countries for r in c.locations]
    excel.table("Locations", list(locations[0]), locations)
    dictionary = _dictionary(countries, columns)
    excel.table("Dictionary", list(dictionary[0]), dictionary)
    selected_sources = [r for r in sources if not r["country_code"] or r["country_code"] in {c.code for c in countries}]
    excel.table("Sources", ["path", "role", "country_code", "bytes", "sha256", "rows"], selected_sources)


def export_integrated(root: Path | None = None, out: Path | None = None) -> dict:
    exporter_hash = sha256(Path(__file__))
    root = (root or Path(__file__).resolve().parents[2]).resolve()
    out = (out or root / "datasets/integrated").resolve()
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite existing destination: {out}")
    inputs, countries, columns = prepare(root)
    # No output is written until all source hashes, row counts, identities and joins pass.
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".integrated-", dir=out.parent))
    overflow = None
    try:
        overflow = Overflow(staging / "overflow_cells.csv")
        master = Excel(staging / "all_countries.xlsx", ["Read_me", *[x[0] for x in COUNTRIES.values()],
                                                       "Coverage", "Locations", "Dictionary", "Sources"])
        outputs = []
        source_records = list(inputs.records.values())
        for country in countries:
            start_overflow_count = overflow.count
            name = COUNTRIES[country.code][0]
            excel = Excel(staging / (name.lower() + ".xlsx"), ["Read_me", *GROUPS, "Locations", "Dictionary", "Sources", "Coverage"])
            for group in GROUPS:
                excel.table(group, columns)
            master.table(name, columns)
            written = Counter()
            for row in country.rows():
                safe = {k: overflow.value(v, row["record_id"], k) for k, v in row.items()}
                excel.append(row["reporting_group"], safe)
                master.append(name, safe)
                written[row["reporting_group"]] += 1
            expected = Counter()
            for record in country.coverage:
                expected[record["reporting_group"]] += record["observations"]
            if written != expected:
                raise ValueError(f"Output row conservation failure: {country.code}")
            _metadata(excel, [country], columns, source_records, overflow.count - start_overflow_count)
            result = excel.save()
            result.update(country_code=country.code, observations=sum(written.values()), reporting_groups=dict(written))
            outputs.append(result)
        _metadata(master, countries, columns, source_records, overflow.count)
        outputs.append(master.save())
        overflow.close()
        overflow = None
        sidecar = staging / "overflow_cells.csv"
        overflow_rows = sum(1 for _ in _csv(sidecar))
        outputs.append({"path": sidecar.name, "bytes": sidecar.stat().st_size,
                        "sha256": sha256(sidecar), "rows": overflow_rows})
        inputs.assert_unchanged()
        if sha256(Path(__file__)) != exporter_hash:
            raise ValueError("Exporter code changed during export")
        manifest = {"schema_version": 1, "scope": "integrated_frozen_study_releases",
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                    "exporter": "rappi_co/export/integrated_deliverable.py", "exporter_sha256": exporter_hash,
                    "observation_key": ["source_dataset", "source_release", *KEY], "columns": columns,
                    "observations": sum(sum(r["observations"] for r in c.coverage) for c in countries),
                    "collection_waves": {"tobacco": sorted({r["source_collection_date"] for c in countries for r in c.coverage if r["source_dataset"] == "tobacco"}),
                                         "beverages": sorted({r["source_collection_date"] for c in countries for r in c.coverage if r["source_dataset"] == "beverages"})},
                    "sources": source_records, "files": outputs,
                    "overflow_cells": overflow_rows, "network_requests": 0,
                    "limitations": ["Separate collection dates; no same-wave comparison", "Finite search coverage; catalog completeness unknown", "SSB candidates do not establish sugar concentration", "Source exclusions and unresolved records retained"]}
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for entry in outputs:
            if sha256(staging / entry["path"]) != entry["sha256"]:
                raise ValueError(f"Output changed before publication: {entry['path']}")
        if out.exists():
            raise FileExistsError(f"Destination appeared during export: {out}")
        staging.rename(out)
        return manifest
    except BaseException:
        if overflow is not None:
            overflow.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="New output directory (default: datasets/integrated); existing directories are refused.")
    args = parser.parse_args(argv)
    result = export_integrated(out=args.out)
    print(json.dumps({"observations": result["observations"], "files": result["files"],
                      "overflow_cells": result["overflow_cells"]}, indent=2))


if __name__ == "__main__":
    main()
