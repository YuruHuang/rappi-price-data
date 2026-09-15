"""Build the four final, category-organized country workbooks.

This is an offline presentation layer over the frozen integrated release. It
does not collect, enrich, reclassify, deduplicate, or impute any product row.
Run ``python -m rappi_co.export.country_product_workbooks --out NEW_DIRECTORY``.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[2]
NUMERIC = set("""price_local original_price_local latitude longitude volume_per_unit_ml
pack_count total_volume_ml price_per_liter_local sugar_g_per_100ml sugar_g_per_serving
serving_volume_ml abv_pct tobacco_volume_ml tobacco_pack_count tobacco_unit_price_local
tobacco_discount_pct tobacco_discount_amount_local tobacco_nicotine_mg_per_ml
tobacco_nicotine_mg_per_pouch tobacco_nicotine_pct tobacco_puff_count discount_pct
source_row""".split())
COUNTRIES = {
    "ar": {"country": "Argentina", "currency": "ARS", "city": "Buenos Aires",
           "filename": "argentina.xlsx"},
    "co": {"country": "Colombia", "currency": "COP", "city": "Bogotá",
           "filename": "colombia.xlsx"},
    "pe": {"country": "Peru", "currency": "PEN", "city": "Lima",
           "filename": "peru.xlsx"},
    "mx": {"country": "Mexico", "currency": "MXN", "city": "Mexico City",
           "filename": "mexico.xlsx"},
}
SHEETS = ("Technical specifications", "Tobacco products", "SSBs", "Water", "Alcohol")
TECHNICAL_FIELDS = (
    "section", "item", "description", "applies_to", "format_unit",
    "coverage", "default_view", "source_field",
)
TECHNICAL_LABELS = (
    "Section", "Item", "Description", "Applies to", "Format / unit",
    "Coverage", "Default view", "Source field",
)
SOURCE_SHEETS = {
    "Tobacco products": "Tobacco",
    "SSBs": "SSB_candidates",
    "Water": "Water",
    "Alcohol": "Alcohol",
}
EXPECTED_COUNTS = {
    "ar": {"Tobacco products": 2325, "SSBs": 6073, "Water": 1464, "Alcohol": 7694},
    "co": {"Tobacco products": 4543, "SSBs": 6116, "Water": 1045, "Alcohol": 6317},
    "pe": {"Tobacco products": 3374, "SSBs": 4673, "Water": 806, "Alcohol": 9469},
    "mx": {"Tobacco products": 597, "SSBs": 6367, "Water": 1741, "Alcohol": 5794},
}
OBSERVATION_KEY = (
    "source_dataset", "source_release", "country_code", "zone_slug", "store_id", "product_id"
)
TEXT_IDS = {
    "record_id", "store_id", "product_id", "master_product_id", "source_product_id",
    "retail_id", "ean", "category_id",
}
JSON_FIELDS = {"attributes_json"}
HIDDEN_FIELDS = {
    "attributes_json", "thumbnail_url",
    "volume_per_unit_ml_source", "volume_per_unit_ml_evidence",
    "pack_count_source", "pack_count_evidence",
    "total_volume_ml_source", "total_volume_ml_evidence",
    "sugar_g_per_100ml_source", "sugar_g_per_100ml_evidence",
    "sugar_g_per_serving_source", "sugar_g_per_serving_evidence",
    "serving_volume_ml_source", "serving_volume_ml_evidence",
    "abv_pct_source", "abv_pct_evidence", "tobacco_discount_amount_local",
    "pack_format_raw", "quantity", "unit_type", "min_purchasing_units", "sale_type",
    "stock", "is_available_raw", "in_stock_raw", "is_possible_stockout_raw",
    "scrape_timestamp", "country_code", "country", "city", "district", "address",
    "latitude", "longitude", "store_type", "parent_store_type", "master_product_id",
    "source_product_id", "retail_id", "ean", "supplier", "menu_section",
    "menu_subsection", "category_id", "source_term", "source_terms", "source_url",
    "source_dataset", "source_release", "source_file", "source_row",
    "requires_medical_prescription", "is_medical_product",
}
SHEET_HIDDEN_FIELDS = {
    "SSBs": {"age_restriction", "identification_required"},
    "Water": {"alcoholic_beverage", "age_restriction", "identification_required"},
    "Alcohol": {"sugar_status", "alcoholic_beverage"},
}
FLAG_FIELDS = {
    "tobacco_age_restriction", "tobacco_has_antismoking", "tobacco_has_menthol",
    "alcoholic_beverage", "age_restriction", "identification_required",
    "requires_medical_prescription", "is_medical_product", "availability",
    "is_available_raw", "in_stock_raw", "is_possible_stockout_raw",
}

# Muted Office colors keep the workbooks easy to distinguish without making
# the category sheets look like a dashboard.  Use full ARGB values so Excel,
# LibreOffice, and preview tools render the fills consistently.
SHEET_ACCENTS = {
    "Technical specifications": "FF44546A",
    "Tobacco products": "FF806000",
    "SSBs": "FFC65911",
    "Water": "FF2F75B5",
    "Alcohol": "FF843C0C",
}
TECHNICAL_SECTION_FILLS = {
    "Overview": "FFD9E2F3",
    "Category summary": "FFE2F0D9",
    "Locations": "FFE2F0D9",
    "Reading notes": "FFFFF2CC",
    "Brand checks": "FFFFF2CC",
    "Reproducibility": "FFEDEDED",
    "Shared fields": "FFEDEDED",
    "Tobacco fields": "FFF2EAD3",
    "SSB fields": "FFFCE4D6",
    "Water fields": "FFDDEBF7",
    "Alcohol fields": "FFF4E1E1",
}
MONEY_FIELDS = {
    "price_local", "original_price_local", "price_per_liter_local",
    "tobacco_discount_amount_local", "tobacco_unit_price_local",
}
FRACTIONAL_PERCENT_FIELDS = {"discount_pct", "tobacco_discount_pct"}
PERCENT_POINT_FIELDS = {"abv_pct", "tobacco_nicotine_pct"}
PERCENT_FIELDS = FRACTIONAL_PERCENT_FIELDS | PERCENT_POINT_FIELDS
COUNT_AND_VOLUME_FIELDS = {
    "volume_per_unit_ml", "pack_count", "total_volume_ml", "serving_volume_ml",
    "tobacco_volume_ml", "tobacco_pack_count", "tobacco_puff_count",
}
CENTER_FIELDS = FLAG_FIELDS | {
    "currency", "country_code", "source_collection_date", "sugar_status",
    "candidate_view_status", "tobacco_stock",
}

CORE_CONTEXT = (
    "availability", "source_collection_date", "zone_slug", "store_name", "store_id",
    "product_id", "record_id",
)
TOBACCO_AUDIT = (
    "tobacco_discount_amount_local", "thumbnail_url", "scrape_timestamp", "country_code", "country",
    "city", "district", "address", "latitude", "longitude", "store_type",
    "parent_store_type", "master_product_id", "ean", "supplier", "menu_section",
    "menu_subsection", "category_id", "source_term", "source_terms", "source_url",
    "source_dataset", "source_release", "source_file", "source_row",
)
BEVERAGE_AUDIT_PROVENANCE = (
    "stock", "is_available_raw", "in_stock_raw", "is_possible_stockout_raw",
    "thumbnail_url", "scrape_timestamp", "country_code", "country", "city", "district", "address",
    "latitude", "longitude", "store_type", "parent_store_type", "master_product_id",
    "source_product_id", "retail_id", "ean", "supplier", "menu_section",
    "menu_subsection", "category_id", "source_term", "source_terms", "source_url",
    "source_dataset", "source_release", "source_file", "source_row",
)
PACKAGE_EVIDENCE = (
    "volume_per_unit_ml_source", "volume_per_unit_ml_evidence", "pack_count_source",
    "pack_count_evidence", "total_volume_ml_source", "total_volume_ml_evidence",
)
RAW_PACKAGE_FIELDS = (
    "pack_format_raw", "quantity", "unit_type", "min_purchasing_units", "sale_type",
)
BEVERAGE_CLASSIFICATION_AUDIT = (
    "attributes_json", "requires_medical_prescription", "is_medical_product",
)
FIELD_SETS = {
    "Tobacco products": (
        "name", "brand", "tobacco_brand_market_scope", "tobacco_study_category",
        "tobacco_product_type", "price_local",
        "original_price_local", "currency", "tobacco_discount_pct", "tobacco_quantity",
        "tobacco_pack_count",
        "tobacco_volume_ml", "tobacco_puff_count", "tobacco_nicotine_mg_per_ml",
        "tobacco_nicotine_mg_per_pouch", "tobacco_nicotine_pct",
        "tobacco_unit_price_local", "tobacco_unit_price_unit", "tobacco_stock",
        "tobacco_age_restriction", "tobacco_has_antismoking", "tobacco_has_menthol",
        *CORE_CONTEXT, *TOBACCO_AUDIT,
    ),
    "SSBs": (
        "name", "price_local", "original_price_local", "currency", "candidate_view_status",
        "sugar_status", "sugar_g_per_100ml", "sugar_g_per_serving",
        "serving_volume_ml", "abv_pct", "alcoholic_beverage",
        "volume_per_unit_ml", "pack_count", "total_volume_ml", "price_per_liter_local",
        "presentation", "beverage_subcategory", "discount_pct", *CORE_CONTEXT,
        "sugar_g_per_100ml_source", "sugar_g_per_100ml_evidence",
        "sugar_g_per_serving_source", "sugar_g_per_serving_evidence",
        "serving_volume_ml_source", "serving_volume_ml_evidence",
        "abv_pct_source", "abv_pct_evidence", *PACKAGE_EVIDENCE, *RAW_PACKAGE_FIELDS,
        *BEVERAGE_CLASSIFICATION_AUDIT, "age_restriction", "identification_required",
        *BEVERAGE_AUDIT_PROVENANCE,
    ),
    "Water": (
        "name", "price_local", "original_price_local", "currency", "volume_per_unit_ml",
        "pack_count", "total_volume_ml", "price_per_liter_local", "presentation",
        "beverage_subcategory", "discount_pct", *CORE_CONTEXT,
        *PACKAGE_EVIDENCE, *RAW_PACKAGE_FIELDS, *BEVERAGE_CLASSIFICATION_AUDIT,
        "alcoholic_beverage", "age_restriction",
        "identification_required", *BEVERAGE_AUDIT_PROVENANCE,
    ),
    "Alcohol": (
        "name", "price_local", "original_price_local", "currency", "abv_pct",
        "volume_per_unit_ml", "pack_count", "total_volume_ml", "price_per_liter_local",
        "presentation", "beverage_subcategory", "discount_pct", "age_restriction",
        "identification_required", *CORE_CONTEXT, "sugar_status", "abv_pct_source", "abv_pct_evidence",
        *PACKAGE_EVIDENCE, *RAW_PACKAGE_FIELDS, *BEVERAGE_CLASSIFICATION_AUDIT,
        "alcoholic_beverage", *BEVERAGE_AUDIT_PROVENANCE,
    ),
}

DISPLAY = {
    "name": "Product name", "brand": "Brand",
    "tobacco_study_category": "Tobacco study category",
    "tobacco_product_type": "Tobacco product type",
    "tobacco_brand_market_scope": "Brand search group",
    "price_local": "Price", "original_price_local": "Original price", "currency": "Currency",
    "tobacco_discount_pct": "Discount (%)",
    "tobacco_discount_amount_local": "Discount amount",
    "tobacco_quantity": "Listed quantity", "tobacco_pack_count": "Pack count",
    "tobacco_volume_ml": "Product volume (mL)", "tobacco_puff_count": "Puff count",
    "tobacco_nicotine_mg_per_ml": "Nicotine (mg/mL)",
    "tobacco_nicotine_mg_per_pouch": "Nicotine (mg/pouch)",
    "tobacco_nicotine_pct": "Nicotine (%)",
    "tobacco_unit_price_local": "Unit price", "tobacco_unit_price_unit": "Unit-price basis",
    "tobacco_stock": "Stock", "tobacco_age_restriction": "Age restriction",
    "tobacco_has_antismoking": "Anti-smoking warning shown",
    "tobacco_has_menthol": "Menthol indicated",
    "sugar_status": "Sugar information status",
    "candidate_view_status": "SSB candidate status",
    "sugar_g_per_100ml": "Sugar (g/100 mL)",
    "sugar_g_per_100ml_source": "Sugar g/100 mL source",
    "sugar_g_per_100ml_evidence": "Sugar g/100 mL evidence",
    "sugar_g_per_serving": "Sugar (g/serving)",
    "sugar_g_per_serving_source": "Sugar g/serving source",
    "sugar_g_per_serving_evidence": "Sugar g/serving evidence",
    "serving_volume_ml": "Serving volume (mL)",
    "serving_volume_ml_source": "Serving-volume source",
    "serving_volume_ml_evidence": "Serving-volume evidence",
    "abv_pct": "Alcohol by volume (%)", "abv_pct_source": "ABV source",
    "abv_pct_evidence": "ABV evidence",
    "volume_per_unit_ml": "Volume per unit (mL)",
    "volume_per_unit_ml_source": "Volume-per-unit source",
    "volume_per_unit_ml_evidence": "Volume-per-unit evidence",
    "pack_count": "Pack count", "pack_count_source": "Pack-count source",
    "pack_count_evidence": "Pack-count evidence", "total_volume_ml": "Total volume (mL)",
    "total_volume_ml_source": "Total-volume source",
    "total_volume_ml_evidence": "Total-volume evidence",
    "price_per_liter_local": "Price per liter", "presentation": "Presentation",
    "pack_format_raw": "Pack format as listed", "quantity": "Listed quantity",
    "unit_type": "Listed unit", "min_purchasing_units": "Minimum purchase units",
    "sale_type": "Sale type",
    "beverage_subcategory": "Beverage subcategory",
    "attributes_json": "Structured attributes (JSON)",
    "alcoholic_beverage": "Alcohol indicator", "age_restriction": "Age restriction",
    "identification_required": "Identification required",
    "requires_medical_prescription": "Medical prescription required",
    "is_medical_product": "Medical product indicator", "discount_pct": "Discount (%)",
    "availability": "Availability", "source_collection_date": "Collection date",
    "stock": "Raw stock value", "is_available_raw": "Raw available flag",
    "in_stock_raw": "Raw in-stock flag",
    "is_possible_stockout_raw": "Raw possible-stockout flag",
    "thumbnail_url": "Product image URL",
    "scrape_timestamp": "Collection timestamp", "country_code": "Country code",
    "country": "Country", "zone_slug": "Delivery zone", "city": "City",
    "district": "District", "address": "Delivery address", "latitude": "Latitude",
    "longitude": "Longitude", "store_name": "Store name", "store_type": "Store type",
    "parent_store_type": "Parent store type", "store_id": "Store ID",
    "product_id": "Product ID", "master_product_id": "Master product ID",
    "source_product_id": "Source product ID", "retail_id": "Retail ID", "ean": "EAN",
    "supplier": "Supplier", "menu_section": "Menu section", "menu_subsection": "Menu subsection",
    "category_id": "Category ID", "source_term": "Search term",
    "source_terms": "All matching search terms", "source_url": "Source URL",
    "source_dataset": "Source dataset", "source_release": "Source release",
    "source_file": "Source file", "source_row": "Source row", "record_id": "Record ID",
}
UNITS = {
    "price_local": "local currency", "original_price_local": "local currency",
    "price_per_liter_local": "local currency/L", "tobacco_discount_amount_local": "local currency",
    "tobacco_unit_price_local": "local currency", "volume_per_unit_ml": "mL",
    "total_volume_ml": "mL", "serving_volume_ml": "mL", "tobacco_volume_ml": "mL",
    "sugar_g_per_100ml": "g/100 mL", "sugar_g_per_serving": "g/serving",
    "abv_pct": "% ABV", "tobacco_nicotine_mg_per_ml": "mg/mL",
    "tobacco_nicotine_mg_per_pouch": "mg/pouch", "tobacco_nicotine_pct": "%",
    "tobacco_discount_pct": "%", "discount_pct": "%", "latitude": "decimal degrees",
    "longitude": "decimal degrees",
}
DEFINITION_OVERRIDES = {
    "presentation": "Package description shown with the product listing.",
    "discount_pct": (
        "Discount relative to the original price, stored as a fraction and displayed as a percentage."
    ),
    "pack_format_raw": "Package-size text retained as it appeared in the listing.",
    "quantity": "Quantity value supplied with the listing.",
    "unit_type": "Unit associated with the listed quantity.",
    "min_purchasing_units": "Minimum number of sale units allowed for purchase.",
    "sale_type": "How the item is sold, as reported by the listing.",
    "source_product_id": "Product identifier from the beverage source record.",
    "retail_id": "Retail identifier from the beverage source record.",
    "scrape_timestamp": (
        "Collection timestamp string preserved in its recorded time basis; "
        "the source did not state a timezone."
    ),
    "alcoholic_beverage": "Source indicator that the listing is marked as an alcoholic beverage.",
    "age_restriction": "Source indicator that an age restriction applies to the listing.",
    "identification_required": "Source indicator that identification is required for purchase.",
    "requires_medical_prescription": "Source indicator that the listing requires a medical prescription.",
    "is_medical_product": "Source indicator that the listing is marked as a medical product.",
    "stock": (
        "Raw stock value returned with the listing when supplied; its platform semantics "
        "were not independently validated. It is not a verified count of units on hand "
        "and is not directly comparable with the tobacco Stock field."
    ),
    "availability": (
        "Normalized listing status derived from the availability and stockout values returned "
        "at collection; it is not a verified inventory count or purchase confirmation."
    ),
    "candidate_view_status": (
        "Membership status for the SSB screening cohort; it does not confirm sweetening or "
        "sugar content."
    ),
    "sugar_status": (
        "Status of explicit sugar wording or evidence in the listing; it is not a nutrient amount."
    ),
    "thumbnail_url": "Product image URL returned with the source listing.",
    "is_available_raw": "Unmodified availability value returned with the source listing.",
    "in_stock_raw": "Unmodified in-stock value returned with the source listing.",
    "is_possible_stockout_raw": (
        "Unmodified possible-stockout value returned with the source listing."
    ),
    "attributes_json": "Structured public product attributes preserved as JSON for audit.",
    "source_term": "First archived discovery query associated with this observation.",
    "source_terms": "All archived discovery queries associated with this observation.",
    "source_url": "Rappi search-response URL from which the observation was collected.",
    "source_file": "Repository-relative path of the frozen source table.",
    "source_row": "One-based row number in the frozen source table; row 1 is the header.",
}


def _manifest_file(manifest: dict, filename: str) -> dict:
    matches = [entry for entry in manifest.get("files", []) if entry.get("path") == filename]
    if len(matches) != 1:
        raise ValueError(f"Integrated manifest must contain one {filename}")
    return matches[0]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verified_bytes(path: Path, entry: dict) -> bytes:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != entry.get("bytes") or digest != entry.get("sha256"):
        raise ValueError(f"Frozen input differs from manifest: {path}")
    return data


def _rows(workbook, sheet: str):
    iterator = workbook[sheet].iter_rows(values_only=False)
    try:
        header_cells = next(iterator)
    except StopIteration as error:
        raise ValueError(f"Empty source sheet: {sheet}") from error
    headers = [cell.value for cell in header_cells]
    if not all(isinstance(field, str) for field in headers) or len(headers) != len(set(headers)):
        raise ValueError(f"Invalid source headers: {sheet}")
    for cells in iterator:
        if any(cell.data_type in {"f", "e"} for cell in cells):
            raise ValueError(f"Formula or error cell in frozen source sheet: {sheet}")
        yield headers, {field: cell.value for field, cell in zip(headers, cells)}


def _plain_rows(workbook, sheet: str) -> list[dict]:
    return [row for _, row in _rows(workbook, sheet)]


def _same(left, right) -> bool:
    if left in (None, "") or right in (None, ""):
        return left in (None, "") and right in (None, "")
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) or isinstance(right, (int, float)):
        try:
            return Decimal(str(left)) == Decimal(str(right))
        except InvalidOperation:
            return False
    return left == right


def _discount_number(value) -> float:
    """Return a validated discount fraction suitable for an Excel percentage cell."""
    try:
        numeric = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"Invalid discount percentage: {value!r}") from error
    if not numeric.is_finite() or not Decimal("0") <= numeric <= Decimal("1"):
        raise ValueError(f"Discount percentage is outside [0, 1]: {value!r}")
    return float(numeric)


def _definitions(dictionary_rows: list[dict], source_dataset: str) -> dict[str, str]:
    by_key = {}
    for row in dictionary_rows:
        key = row.get("column")
        dataset = row.get("source_dataset")
        if not key:
            continue
        rank = 0 if dataset == source_dataset else 1 if dataset == "integration" else 2
        current = by_key.get(key)
        if current is None or rank < current[0]:
            by_key[key] = (rank, str(row.get("definition") or "Preserved frozen source field."))
    return {key: value for key, (_, value) in by_key.items()}


def _brand_matrix(root: Path, integrated_manifest: dict | None = None) -> \
        tuple[dict[tuple[str, str], dict], list[dict]]:
    manifest_path = root / "docs/brand_coverage_matrix_manifest.json"
    csv_path = root / "docs/brand_coverage_matrix.csv"
    manifest_bytes = manifest_path.read_bytes()
    csv_bytes = csv_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    output = manifest.get("output") or {}
    if (manifest.get("schema_version") != 1 or manifest.get("rows") != 12
            or output.get("path") != "docs/brand_coverage_matrix.csv"
            or output.get("bytes") != len(csv_bytes)
            or output.get("sha256") != hashlib.sha256(csv_bytes).hexdigest()):
        raise ValueError("Brand coverage matrix differs from its manifest")
    with io.StringIO(csv_bytes.decode("utf-8-sig"), newline="") as handle:
        rows = list(csv.DictReader(handle))
    keyed = {(row["country_code"], row["family"]): row for row in rows}
    expected = {(code, family) for code in COUNTRIES for family in ("water", "ssb", "alcohol")}
    if set(keyed) != expected or len(rows) != 12:
        raise ValueError("Brand coverage matrix must contain 12 unique country-family rows")
    for row in rows:
        if int(row["local_observation_count"]) <= 0 or int(row["international_observation_count"]) <= 0:
            raise ValueError("Brand coverage examples require observed archived matches")
        release = (manifest.get("source_release_generations") or {}).get(row["country_code"])
        audit_hash = (manifest.get("input_sha256") or {}).get(row["source_audit_relative_path"])
        if row.get("source_run_id") != release or row.get("source_audit_sha256") != audit_hash:
            raise ValueError("Brand coverage row differs from its declared source release")
    if integrated_manifest is not None:
        integrated_sources = {entry.get("path"): entry.get("sha256")
                              for entry in integrated_manifest.get("sources", [])}
        for relative, digest in (manifest.get("input_sha256") or {}).items():
            if relative == "config/beverages.yml":
                if sha256(root / relative) != digest:
                    raise ValueError("Brand coverage configuration hash is stale")
            elif integrated_sources.get(relative) != digest:
                raise ValueError(f"Brand coverage source is outside the integrated release: {relative}")
    inputs = [
        {"path": str(manifest_path.relative_to(root)), "role": "brand_coverage_manifest",
         "bytes": len(manifest_bytes), "sha256": hashlib.sha256(manifest_bytes).hexdigest()},
        {"path": str(csv_path.relative_to(root)), "role": "brand_coverage_matrix",
         "bytes": len(csv_bytes), "sha256": hashlib.sha256(csv_bytes).hexdigest()},
    ]
    return keyed, inputs


class CountryExcel:
    """Write a readable, literal-value workbook without formula coercion."""

    def __init__(self, path: Path, country: str | None = None):
        self.path = path
        self.workbook = Workbook(write_only=True)
        self.workbook.properties.creator = "Rappi product study"
        self.workbook.properties.title = (
            f"Rappi product listings — {country}"
            if country else "Rappi country product listings"
        )
        self.sheets = {name: self.workbook.create_sheet(name) for name in SHEETS}
        self.fields: dict[str, tuple[str, ...]] = {}
        self.counts = Counter()
        self.technical_section = None
        self.body_font = Font(name="Calibri", size=10, color="FF222222")
        self.header_font = Font(name="Calibri", size=10, bold=True, color="FFFFFFFF")
        self.header_border = Border(
            bottom=Side(style="medium", color="FFD9E2F3")
        )
        self.section_border = Border(
            top=Side(style="thin", color="FF9EADBA")
        )
        self.section_font = Font(name="Calibri", size=10, bold=True, color="FF333333")

    @staticmethod
    def _column_width(field: str, label: str) -> float:
        widths = {
            "section": 20,
            "item": 30,
            "description": 68,
            "applies_to": 24,
            "format_unit": 18,
            "coverage": 38,
            "default_view": 18,
            "source_field": 28,
            "name": 40,
            "brand": 22,
            "currency": 10,
            "address": 38,
            "presentation": 30,
            "pack_format_raw": 28,
            "source_term": 25,
            "source_terms": 40,
            "source_url": 44,
            "source_file": 38,
            "record_id": 32,
            "attributes_json": 44,
            "scrape_timestamp": 22,
            "source_collection_date": 16,
            "latitude": 14,
            "longitude": 14,
        }
        if field in widths:
            return widths[field]
        if field in TEXT_IDS:
            return 24
        if field in MONEY_FIELDS | PERCENT_FIELDS | COUNT_AND_VOLUME_FIELDS | NUMERIC:
            return 14
        if field in CENTER_FIELDS:
            return 18
        return max(12, min(28, len(label) + 2))

    @staticmethod
    def _number_format(field: str) -> str:
        if field in MONEY_FIELDS:
            return "#,##0.##"
        if field in FRACTIONAL_PERCENT_FIELDS:
            return "0.0%"
        if field in PERCENT_POINT_FIELDS:
            return '0.0"%"'
        if field in COUNT_AND_VOLUME_FIELDS:
            return "#,##0.##"
        if field == "source_row":
            return "#,##0"
        if field in {"latitude", "longitude"}:
            return "0.000000"
        return "0.########"

    def table(self, sheet: str, fields: tuple[str, ...], labels: tuple[str, ...] | None = None):
        if len(fields) != len(set(fields)):
            raise ValueError(f"Duplicate output fields: {sheet}")
        labels = labels or tuple(DISPLAY[field] for field in fields)
        if len(labels) != len(set(labels)):
            raise ValueError(f"Duplicate output labels: {sheet}")
        self.fields[sheet] = fields
        worksheet = self.sheets[sheet]
        worksheet.freeze_panes = "C2" if sheet == "Technical specifications" else "B2"
        worksheet.sheet_view.showGridLines = sheet != "Technical specifications"
        worksheet.sheet_view.zoomScale = 90
        worksheet.sheet_view.zoomScaleNormal = 90
        worksheet.sheet_properties.tabColor = SHEET_ACCENTS[sheet]
        worksheet.sheet_properties.outlinePr.summaryRight = True
        worksheet.sheet_format.defaultRowHeight = 18
        worksheet.row_dimensions[1].height = 30
        worksheet.print_title_rows = "1:1"
        worksheet.print_options.gridLines = False
        worksheet.page_setup.orientation = "landscape"
        if sheet == "Technical specifications":
            worksheet.oddFooter.left.text = "Rappi product study"
            worksheet.oddFooter.center.text = sheet
            worksheet.oddFooter.right.text = "Page &P of &N"
            for part in (worksheet.oddFooter.left, worksheet.oddFooter.center,
                         worksheet.oddFooter.right):
                part.size = 8
                part.font = "Calibri"
        for index, (field, label) in enumerate(zip(fields, labels), 1):
            dimension = worksheet.column_dimensions[get_column_letter(index)]
            dimension.width = self._column_width(field, label)
            dimension.hidden = (
                field in HIDDEN_FIELDS or field in SHEET_HIDDEN_FIELDS.get(sheet, set())
            )
            if dimension.hidden:
                dimension.outlineLevel = 1
        cells = []
        header_fill = PatternFill("solid", fgColor=SHEET_ACCENTS[sheet])
        for label in labels:
            cell = WriteOnlyCell(worksheet, label)
            cell.font, cell.fill, cell.border = (
                self.header_font, header_fill, self.header_border
            )
            cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            cell.data_type, cell.number_format = "s", "@"
            cells.append(cell)
        worksheet.append(cells)

    def append(self, sheet: str, row: dict):
        worksheet = self.sheets[sheet]
        is_technical = sheet == "Technical specifications"
        section = str(row.get("section") or "") if is_technical else ""
        technical_group = section
        starts_section = is_technical and technical_group != self.technical_section
        cells = []
        for field in self.fields[sheet]:
            value = row.get(field)
            if value is None or value == "":
                cells.append(None)
                continue
            if field == "discount_pct" and isinstance(value, str):
                value = _discount_number(value)
            if isinstance(value, str):
                if len(value.encode("utf-16-le")) // 2 > 32767 or ILLEGAL_CHARACTERS_RE.search(value):
                    raise ValueError(f"Unsafe Excel text: {sheet}/{field}")
            cell = WriteOnlyCell(worksheet, value)
            cell.font = self.body_font
            if isinstance(value, str):
                cell.data_type, cell.number_format = "s", "@"
            elif isinstance(value, bool):
                cell.data_type = "b"
            elif field in NUMERIC or isinstance(value, (int, float)):
                cell.number_format = self._number_format(field)
            if is_technical:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                if field in {"section", "item"}:
                    cell.font = self.section_font
                if field == "section":
                    cell.fill = PatternFill(
                        "solid", fgColor=TECHNICAL_SECTION_FILLS.get(
                            technical_group, "FFF2F2F2"
                        )
                    )
                if starts_section:
                    cell.border = self.section_border
            elif field in CENTER_FIELDS:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            cells.append(cell)
        if is_technical:
            text = str(row.get("description") or "")
            coverage = str(row.get("coverage") or "")
            line_count = max((len(section) + 19) // 20, (len(text) + 62) // 63,
                             (len(coverage) + 34) // 35, 1)
            worksheet.row_dimensions[self.counts[sheet] + 2].height = min(
                105, max(22, 14 * line_count + 5)
            )
            self.technical_section = technical_group
        worksheet.append(cells)
        self.counts[sheet] += 1

    def save(self) -> dict:
        for name, worksheet in self.sheets.items():
            worksheet.auto_filter.ref = (
                f"A1:{get_column_letter(len(self.fields[name]))}{self.counts[name] + 1}"
            )
        self.workbook.save(self.path)
        with zipfile.ZipFile(self.path) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"Corrupt output workbook: {self.path}")
        return {"path": self.path.name, "bytes": self.path.stat().st_size,
                "sha256": sha256(self.path), "sheet_rows": dict(self.counts)}


def _location_rows(workbook, code: str) -> list[dict]:
    keyed = {}
    for row in _plain_rows(workbook, "Locations"):
        if row.get("country_code") != code:
            raise ValueError("Location country differs from workbook")
        key = row["zone_slug"]
        comparable = {field: row.get(field) for field in
                      ("country", "currency", "address", "district", "latitude", "longitude")}
        if key in keyed:
            if any(not _same(keyed[key].get(field), value) for field, value in comparable.items()):
                raise ValueError("Tobacco and beverage locations differ")
        else:
            keyed[key] = comparable | {"zone_slug": key}
    if len(keyed) != 2:
        raise ValueError("Each country workbook requires exactly two configured locations")
    return [keyed[key] for key in sorted(keyed)]


def _technical_rows(code: str, locations: list[dict], counts: Counter,
                    nonblank: dict[str, Counter], definitions: dict[str, dict],
                    brand_rows: dict[tuple[str, str], dict]) -> list[dict]:
    """Build a compact workbook guide and de-duplicated data dictionary."""
    meta = COUNTRIES[code]
    total = sum(counts.values())
    rows: list[dict] = []

    def add(section: str, item: str, description: str, applies_to: str = "",
            format_unit: str = "", coverage: str = "",
            default_view: str = "", source_field: str = "") -> None:
        rows.append({
            "section": section,
            "item": item,
            "description": description,
            "applies_to": applies_to,
            "format_unit": format_unit,
            "coverage": coverage,
            "default_view": default_view,
            "source_field": source_field,
        })

    add("Overview", "Workbook", f"Rappi product listings — {meta['country']}. "
        "The four product categories are provided on separate worksheets.")
    add("Overview", "Country and currency",
        f"{meta['country']} ({code.upper()}); prices are in {meta['currency']}. "
        "No currency conversion was applied.")
    add("Overview", "Unit of observation",
        "One product listing at one store, delivery location and collection time. "
        "The same product may appear in more than one store or location.")
    add("Overview", "Workbook total", f"{total:,} observations in this workbook. "
        "The four country workbooks contain 68,398 observations in total.")
    add("Overview", "Collection dates",
        "Tobacco: 16 August 2026. Beverages: 10 September 2026. The dates refer "
        "to separate collection waves, so their prices are not contemporaneous.")
    add("Overview", "Observation key",
        "source_dataset + source_release + country_code + zone_slug + store_id + "
        "product_id. Record ID is the stable row identifier.")
    add("Overview", "Relationship to the integrated data",
        "The integrated release has 95,688 observations. These workbooks contain the "
        "68,398 target observations and leave out 27,290 comparison, review and excluded rows.")

    category_notes = {
        "Tobacco products": "Published tobacco and nicotine inclusion set.",
        "SSBs": ("Screening cohort. All rows have unconfirmed sweetening status, and this "
                 "release has no quantitative sugar measurements. Alcohol fields are shown "
                 "as cross-category checks for candidates that may require review."),
        "Water": "Published plain-water set.",
        "Alcohol": ("Products with supported alcohol identity. Alcohol by volume is "
                    "shown only when the listing evidence states it."),
    }
    for sheet in SHEETS[1:]:
        add("Category summary", sheet, category_notes[sheet], sheet,
            coverage=f"{counts[sheet]:,} rows")

    for index, location in enumerate(locations, 1):
        add("Locations", f"Delivery location {index}",
            f"{location['address']} ({location['district']}); latitude "
            f"{location['latitude']}, longitude {location['longitude']}.",
            applies_to=location["zone_slug"])

    reading_notes = [
        ("Missing values", "A blank cell means the value was unavailable or could not be "
         "supported. It does not mean zero."),
        ("Repeated listings", "Repeated products across stores or delivery locations are "
         "intentional and should remain separate for price and availability analysis."),
        ("Volume and pack size", "Volume per unit, pack count and total sale volume are "
         "separate measures. Price per liter is shown only when total volume is supported."),
        ("Percentages", "Discounts are stored as numeric Excel percentages. Alcohol by "
         "volume and nicotine percentage are percentage-point values stated in the listing evidence."),
        ("Sugar", "Blank sugar fields mean that quantitative sugar information is unknown, "
         "not that the product contains no sugar."),
        ("Availability and stock", "Availability is a normalized listing status at collection. "
         "Raw beverage stock values are retained in hidden columns but are not verified "
         "inventory counts."),
        ("Product titles", "Product name is the title from the listing or search result. "
         "Product-detail pages are not included."),
        ("Geographic scope", f"The study used two delivery locations in {meta['city']}. "
         "The results are not estimates of national availability or market share."),
        ("Source scope", "The file reflects a finite search of Rappi listings at the recorded "
         "times; it is not a complete or continuously updated catalog."),
    ]
    for item, description in reading_notes:
        add("Reading notes", item, description)

    add("Brand checks", "How to read the examples",
        "The examples confirm that selected country-market and international names appeared "
        "in the archived search results. These labels describe the search check; they do not "
        "establish ownership, manufacturing origin, import status or market share. The beverage "
        "source did not provide a validated row-level brand field, so brands were not inferred "
        "from product titles.")
    add("Brand checks", "Tobacco products",
        "Brand and Brand search group are retained on the Tobacco products worksheet when "
        "they were assigned in the source data.", applies_to="Tobacco products")
    for family, sheet in (("water", "Water"), ("ssb", "SSBs"), ("alcohol", "Alcohol")):
        item = brand_rows[(code, family)]
        note = (
            f"Archived title matches include {item['local_brand']} as the country-market "
            f"example ({int(item['local_observation_count']):,} matches) and "
            f"{item['international_brand']} as the international example "
            f"({int(item['international_observation_count']):,} matches)."
        )
        if family == "ssb":
            note += (" Counts use the full beverage discovery audit, which also includes "
                     "review and comparison rows outside the SSB worksheet.")
        add("Brand checks", sheet, note, applies_to=sheet)

    add("Reproducibility", "Source workbook",
        f"datasets/integrated/{meta['filename']}")
    add("Reproducibility", "Manifest",
        "The accompanying manifest.json records the input and output file sizes, SHA-256 "
        "hashes, row counts and exporter version. The export makes no network requests.")

    uses: dict[str, list[str]] = {}
    ordered_fields: list[str] = []
    for sheet in SHEETS[1:]:
        for field in FIELD_SETS[sheet]:
            if field not in uses:
                uses[field] = []
                ordered_fields.append(field)
            uses[field].append(sheet)

    def definition_for(field: str, sheets: list[str]) -> str:
        if field in DEFINITION_OVERRIDES:
            text = DEFINITION_OVERRIDES[field]
        else:
            candidates = []
            if "Tobacco products" in sheets:
                candidates.append(definitions["tobacco"].get(field, ""))
            if any(sheet != "Tobacco products" for sheet in sheets):
                candidates.append(definitions["beverages"].get(field, ""))
            useful = [value.strip() for value in candidates if value and not value.lower().startswith(
                ("source or provenance field:", "retained source field; no definition")
            )]
            if useful:
                text = useful[0]
            elif field in TEXT_IDS:
                text = "Identifier retained from the source release."
            elif field in NUMERIC:
                text = "Numeric value retained from the source release."
            else:
                text = "Value retained from the source listing or collection record."
        text = text.strip()
        return text if text.endswith((".", "?", "!")) else f"{text}."

    group_order = ["Shared fields", "Tobacco fields", "SSB fields", "Water fields",
                   "Alcohol fields"]
    grouped = {group: [] for group in group_order}
    for field in ordered_fields:
        sheets = uses[field]
        group = "Shared fields" if len(sheets) > 1 else {
            "Tobacco products": "Tobacco fields",
            "SSBs": "SSB fields",
            "Water": "Water fields",
            "Alcohol": "Alcohol fields",
        }[sheets[0]]
        grouped[group].append(field)

    short_sheet = {"Tobacco products": "Tobacco", "SSBs": "SSBs",
                   "Water": "Water", "Alcohol": "Alcohol"}
    for group in group_order:
        for field in grouped[group]:
            sheets = uses[field]
            value_type = ("Number" if field in NUMERIC else
                          "Text indicator" if field in FLAG_FIELDS else "Text")
            unit = UNITS.get(field, "")
            format_unit = f"{value_type} ({unit})" if unit else value_type
            coverage = "; ".join(
                f"{short_sheet[sheet]}: {nonblank[sheet][field]:,}/{counts[sheet]:,}"
                for sheet in sheets
            )
            visibility = []
            for sheet in sheets:
                hidden = field in HIDDEN_FIELDS or field in SHEET_HIDDEN_FIELDS.get(sheet, set())
                visibility.append((sheet, "Hidden" if hidden else "Shown"))
            states = {state for _, state in visibility}
            default_view = states.pop() if len(states) == 1 else "; ".join(
                f"{short_sheet[sheet]}: {state.lower()}" for sheet, state in visibility
            )
            add(group, DISPLAY[field], definition_for(field, sheets),
                applies_to=", ".join(sheets), format_unit=format_unit,
                coverage=coverage, default_view=default_view, source_field=field)
    return rows


def _validate_output(path: Path, source_bytes: bytes, code: str) -> None:
    output = load_workbook(path, read_only=True, data_only=False)
    source = load_workbook(io.BytesIO(source_bytes), read_only=True, data_only=False)
    try:
        if output.sheetnames != list(SHEETS):
            raise ValueError(f"Wrong output sheet order: {path}")
        technical = output["Technical specifications"].iter_rows(values_only=True)
        if next(technical) != TECHNICAL_LABELS:
            raise ValueError("Invalid Technical specifications header")
        if sum(1 for _ in technical) < 100:
            raise ValueError("Technical specifications is incomplete")
        seen = set()
        for output_sheet, source_sheet in SOURCE_SHEETS.items():
            out_rows = output[output_sheet].iter_rows(values_only=False)
            labels = [cell.value for cell in next(out_rows)]
            expected_labels = [DISPLAY[field] for field in FIELD_SETS[output_sheet]]
            if labels != expected_labels:
                raise ValueError(f"Output headers differ: {output_sheet}")
            source_rows = _rows(source, source_sheet)
            count = 0
            for cells, (_, source_row) in zip(out_rows, source_rows, strict=True):
                count += 1
                values = [cell.value for cell in cells]
                if any(cell.data_type in {"f", "e"} for cell in cells):
                    raise ValueError(f"Formula or error cell in {output_sheet}")
                for field, value in zip(FIELD_SETS[output_sheet], values):
                    if not _same(value, source_row.get(field)):
                        raise ValueError(f"Output changed source value: {output_sheet}/{count}/{field}")
                    if field in TEXT_IDS and value not in (None, "") and not isinstance(value, str):
                        raise ValueError(f"Identifier is not text: {output_sheet}/{field}")
                    if field in JSON_FIELDS and value not in (None, ""):
                        json.loads(value)
                record_id = source_row["record_id"]
                if record_id in seen:
                    raise ValueError(f"Duplicate record_id in country workbook: {record_id}")
                seen.add(record_id)
            if count != EXPECTED_COUNTS[code][output_sheet]:
                raise ValueError(f"Output row count differs: {code}/{output_sheet}")
        if len(seen) != sum(EXPECTED_COUNTS[code].values()):
            raise ValueError("Country output does not contain the expected unique records")
    finally:
        output.close()
        source.close()


def export_country_workbooks(out: Path, root: Path = ROOT) -> dict:
    """Create a new, verified directory containing the four final workbooks."""
    root, out = root.resolve(), Path(out).resolve()
    if out.exists():
        raise FileExistsError(f"Destination must be new: {out}")
    exporter_path = Path(__file__).resolve()
    exporter_hash = sha256(exporter_path)
    integrated_manifest_path = root / "datasets/integrated/manifest.json"
    integrated_manifest_bytes = integrated_manifest_path.read_bytes()
    integrated_manifest = json.loads(integrated_manifest_bytes.decode("utf-8"))
    if (integrated_manifest.get("schema_version") != 1
            or integrated_manifest.get("observations") != 95688
            or integrated_manifest.get("network_requests") != 0):
        raise ValueError("Unexpected integrated release manifest")
    brand_rows, brand_inputs = _brand_matrix(root, integrated_manifest)
    inputs = [{"path": "datasets/integrated/manifest.json", "role": "integrated_manifest",
               "bytes": len(integrated_manifest_bytes),
               "sha256": hashlib.sha256(integrated_manifest_bytes).hexdigest()}, *brand_inputs,
              {"path": str(exporter_path.relative_to(root)), "role": "exporter",
               "bytes": exporter_path.stat().st_size, "sha256": exporter_hash}]
    source_payloads = {}
    for code, meta in COUNTRIES.items():
        entry = _manifest_file(integrated_manifest, meta["filename"])
        expected_groups = {
            "Tobacco": EXPECTED_COUNTS[code]["Tobacco products"],
            "Water": EXPECTED_COUNTS[code]["Water"],
            "SSB_candidates": EXPECTED_COUNTS[code]["SSBs"],
            "Alcohol": EXPECTED_COUNTS[code]["Alcohol"],
        }
        if any((entry.get("reporting_groups") or {}).get(group) != count
               for group, count in expected_groups.items()):
            raise ValueError(f"Integrated target counts differ: {code}")
        source_path = root / "datasets/integrated" / meta["filename"]
        source_payloads[code] = (_verified_bytes(source_path, entry), entry, source_path)
        inputs.append({"path": str(source_path.relative_to(root)),
                       "role": f"integrated_country_{code}",
                       "bytes": entry["bytes"], "sha256": entry["sha256"]})

    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".country-products-", dir=out.parent))
    files = []
    try:
        for code, meta in COUNTRIES.items():
            source_bytes, source_entry, source_path = source_payloads[code]
            source = load_workbook(io.BytesIO(source_bytes), read_only=True, data_only=False)
            excel = CountryExcel(staging / meta["filename"], meta["country"])
            counts = Counter()
            nonblank = {sheet: Counter() for sheet in SHEETS[1:]}
            seen = set()
            try:
                if any(sheet not in source.sheetnames for sheet in
                       [*SOURCE_SHEETS.values(), "Dictionary", "Locations"]):
                    raise ValueError(f"Integrated workbook is missing required sheets: {code}")
                dictionary_rows = _plain_rows(source, "Dictionary")
                definitions = {
                    "tobacco": _definitions(dictionary_rows, "tobacco"),
                    "beverages": _definitions(dictionary_rows, "beverages"),
                }
                locations = _location_rows(source, code)
                excel.table("Technical specifications", TECHNICAL_FIELDS, TECHNICAL_LABELS)
                for output_sheet, source_sheet in SOURCE_SHEETS.items():
                    fields = FIELD_SETS[output_sheet]
                    excel.table(output_sheet, fields)
                    expected_headers = None
                    expected_group = source_sheet
                    for headers, row in _rows(source, source_sheet):
                        if expected_headers is None:
                            expected_headers = headers
                            if list(integrated_manifest.get("columns") or []) != headers:
                                raise ValueError(f"Integrated source schema differs: {code}/{source_sheet}")
                            missing = set(fields) - set(headers)
                            if missing:
                                raise ValueError(f"Missing requested fields: {output_sheet}/{sorted(missing)}")
                        if row.get("country_code") != code or row.get("country") != meta["country"]:
                            raise ValueError(f"Country mismatch: {code}/{source_sheet}")
                        if row.get("reporting_group") != expected_group:
                            raise ValueError(f"Reporting-group mismatch: {code}/{source_sheet}")
                        if row.get("currency") != meta["currency"]:
                            raise ValueError(f"Currency mismatch: {code}/{source_sheet}")
                        if any(not isinstance(row.get(field), str) for field in OBSERVATION_KEY):
                            raise ValueError(f"Observation identity is not text: {code}/{source_sheet}")
                        record_id = row.get("record_id")
                        if not isinstance(record_id, str) or record_id in seen:
                            raise ValueError(f"Missing or duplicate record_id: {code}/{source_sheet}")
                        for field in TEXT_IDS:
                            if row.get(field) not in (None, "") and not isinstance(row[field], str):
                                raise ValueError(f"Source identifier is not text: {code}/{field}")
                        for field in JSON_FIELDS & set(fields):
                            if row.get(field) not in (None, ""):
                                json.loads(row[field])
                        seen.add(record_id)
                        excel.append(output_sheet, row)
                        counts[output_sheet] += 1
                        for field in fields:
                            nonblank[output_sheet][field] += row.get(field) not in (None, "")
                    if counts[output_sheet] != EXPECTED_COUNTS[code][output_sheet]:
                        raise ValueError(f"Source row count differs: {code}/{output_sheet}")
                technical = _technical_rows(
                    code, locations, counts, nonblank, definitions, brand_rows,
                )
                for row in technical:
                    excel.append("Technical specifications", row)
                result = excel.save()
            finally:
                source.close()
            _validate_output(staging / meta["filename"], source_bytes, code)
            result.update(country_code=code, country=meta["country"], currency=meta["currency"],
                          product_rows=sum(counts.values()),
                          reporting_groups={sheet: counts[sheet] for sheet in SHEETS[1:]},
                          source_sha256=source_entry["sha256"])
            files.append(result)
            if source_path.stat().st_size != source_entry["bytes"] or sha256(source_path) != source_entry["sha256"]:
                raise ValueError(f"Frozen country input changed during export: {code}")

        readme = """# Final country product workbooks

This directory contains one final workbook for Argentina, Colombia, Peru and
Mexico. Each workbook has exactly five sheets in this order: `Technical
specifications`, `Tobacco products`, `SSBs`, `Water`, and `Alcohol`.

The four files contain 68,398 study observations. Every row in the `SSBs`
worksheets belongs to an unconfirmed screening cohort; all quantitative sugar
fields are blank, and blank means unknown rather than zero. Alcohol fields are
shown there as cross-category checks. Product-detail pages are not included.
The beverage source did not provide a validated row-level brand field, so
beverage brands were not inferred from titles. `Technical specifications` is a
plain-language workbook guide followed by a structured data dictionary. Each
category sheet starts with category measures and selected source context.
Additional raw source fields, measurement evidence and provenance are grouped
in hidden columns to the right; the guide marks every field Shown or Hidden.

Availability is a normalized listing status at collection. Raw beverage stock
values are retained in hidden columns but are not verified inventory counts.

Rebuild offline into a new directory:

```sh
python -m rappi_co.export.country_product_workbooks --out data/country_products_rebuild
```

`manifest.json` records the exact inputs, columns, output hashes, and counts.
"""
        readme_path = staging / "README.md"
        readme_path.write_text(readme, encoding="utf-8")
        manifest = {
            "schema_version": 2,
            "status": "final_country_category_workbooks",
            "scope": "frozen_target_observations_four_countries_five_sheets",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "network_requests": 0,
            "countries": list(COUNTRIES),
            "sheet_order": list(SHEETS),
            "observation_key": list(OBSERVATION_KEY),
            "product_rows": sum(sum(values.values()) for values in EXPECTED_COUNTS.values()),
            "excluded_integrated_observations": 95688 - 68398,
            "columns": {sheet: [{"source_field": field, "header": DISPLAY[field]}
                                  for field in FIELD_SETS[sheet]] for sheet in SHEETS[1:]},
            "files": files,
            "documentation": {"path": "README.md", "bytes": readme_path.stat().st_size,
                              "sha256": sha256(readme_path)},
            "inputs": inputs,
            "limitations": [
                "every SSB row has unconfirmed sweetening status",
                "quantitative sugar fields contain no measurements in this frozen beverage release",
                "separate August tobacco and September beverage collection waves",
                "finite search protocol at two delivery locations per country; catalog and national completeness unknown",
                "brand labels in the coverage audit are discovery roles, not ownership or origin",
                "no renewed product-detail collection and no product-information enrichment",
            ],
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        for entry in [*files, manifest["documentation"]]:
            path = staging / entry["path"]
            if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
                raise ValueError(f"Generated output changed before publication: {entry['path']}")
        for entry in inputs:
            path = root / entry["path"]
            if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
                raise ValueError(f"Input changed during export: {entry['path']}")
        if sha256(exporter_path) != exporter_hash:
            raise ValueError("Exporter changed during export")
        if out.exists():
            raise FileExistsError(f"Destination must be new: {out}")
        staging.rename(out)
        return manifest
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    result = export_country_workbooks(args.out)
    print(json.dumps({key: result[key] for key in
                      ("status", "product_rows", "sheet_order", "network_requests")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
