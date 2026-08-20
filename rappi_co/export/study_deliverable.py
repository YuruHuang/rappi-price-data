"""Build country-aware tobacco data files from the configured search results."""
from __future__ import annotations

import glob
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from rappi_co.classify.tobacco_classifier import _matches, _normalize
from rappi_co.configs import STUDY_CATEGORIES, brand_variants, load_study_profile
from rappi_co.enrich.tobacco_fields import enrich_tobacco_fields


ROOT = Path(__file__).resolve().parents[2]
STUDY_CONFIG = ROOT / "config" / "study"
_ARTIFACT_TOKEN_RE = re.compile(r"\d{8}_\d{6}_\d{6}")

CLASSIFICATION_COLS = [
    "primary_class", "product_type", "confidence", "method", "rationale", "flags",
]
STUDY_PRODUCT_TYPES = {
    "nicotine_pouch": "nicotine_pouches",
    "vape": "electronic_cigarettes",
    "vape_disposable": "electronic_cigarettes",
    "vape_pod": "electronic_cigarettes",
    "vape_liquid": "electronic_cigarettes",
    "heated_tobacco": "heated_tobacco",
    "cigarette": "cigarettes",
}
ITEM_COLS = [
    "country_code", "country", "city", "currency",
    "zone_slug", "address", "district", "latitude", "longitude",
    "product_id", "master_product_id", "store_id", "store_type", "store_name",
    "parent_store_type", "name", "brand", "brand_market_scope", "ean", "supplier",
    "menu_section", "menu_subsection", "category_id",
    "price_local", "original_price_local", "discount_pct", "discount_amount_local",
    "unit_price_local", "unit_price_unit", "volume_ml", "pack_count", "quantity",
    "availability", "stock", "age_restriction", "has_antismoking", "has_menthol",
    "primary_class", "study_category", "product_type", "confidence", "method", "rationale",
    "flags",
    "nicotine_mg_per_ml", "nicotine_mg_per_pouch", "nicotine_pct", "puff_count",
    "thumbnail_url", "source_term", "source_terms", "source_url", "scrape_timestamp",
]
STORE_COLS = [
    "country_code", "zone_slug", "store_id", "store_type", "store_name",
    "parent_store_type", "n_tobacco_observations", "product_types",
]
LOCATION_COLS = [
    "country_code", "country", "city", "currency", "zone_slug", "address", "district",
    "latitude", "longitude", "n_tobacco_observations",
]
ITEM_DEFINITIONS = {
    "country_code": "ISO alpha-2 country code.",
    "country": "Country name.",
    "city": "Sampled Rappi city.",
    "currency": "ISO 4217 currency used by the local-price fields.",
    "zone_slug": "Configured delivery-location slug for this observation.",
    "address": "Public landmark address used as the delivery point.",
    "district": "District or neighborhood containing the delivery point.",
    "latitude": "Configured WGS84 delivery latitude.",
    "longitude": "Configured WGS84 delivery longitude.",
    "product_id": "Rappi product identifier; use with zone_slug and store_id.",
    "master_product_id": "Rappi master-product identifier when supplied.",
    "store_id": "Rappi store identifier at the sampled delivery point.",
    "store_type": "Rappi store-type code.",
    "store_name": "Store display name.",
    "parent_store_type": "Rappi parent store-type category.",
    "name": "Product name shown by Rappi.",
    "brand": "Reviewed configured brand matched in name/source brand; source brand is the fallback.",
    "brand_market_scope": "international or local_market; local_market does not imply local ownership.",
    "ean": "Barcode or GTIN when supplied.",
    "supplier": "Supplier or importer when supplied.",
    "menu_section": "Store aisle or category returned for the product.",
    "menu_subsection": "Store subsection when supplied.",
    "category_id": "Rappi category identifier, preserved as text.",
    "price_local": "Current product or pack price in the row currency.",
    "original_price_local": "Pre-discount price in the row currency when supplied.",
    "discount_pct": "Derived discount share: (original-current)/original, from 0 to 1.",
    "discount_amount_local": "Derived original price minus current price, floored at zero and rounded to two decimal places.",
    "unit_price_local": "Derived price per credible parsed pack unit in the row currency.",
    "unit_price_unit": "Unit used for unit_price_local; und means one item or stick.",
    "volume_ml": "Millilitres parsed from source fields or product text.",
    "pack_count": "Credible smallest units per pack; cigarette cartons include the leading multiplier and reviewed TEREA/HEETS cajetillas use 20 sticks, multiplied by an explicit carton count. Ambiguous multi-can/combo denominators are blank.",
    "quantity": "Raw Rappi quantity field.",
    "availability": "Availability status returned by Rappi.",
    "stock": "Stock value returned by Rappi when supplied.",
    "age_restriction": "Age-restriction value returned by Rappi.",
    "has_antismoking": "Rappi anti-smoking or health-warning signal.",
    "has_menthol": "Menthol signal derived by the existing enrichment rules.",
    "primary_class": "Deterministic classifier verdict; exported item rows are tobacco.",
    "study_category": "One of the four configured product categories.",
    "product_type": "Classifier subtype used to map the row into a product category.",
    "confidence": "Classifier confidence: high, medium, or low.",
    "method": "Deterministic classification rule that fired.",
    "rationale": "Short explanation of the classification evidence.",
    "flags": "Classifier and review flags, pipe-separated; mixed_bundle means component-specific enrichment and unit denominators are intentionally blank.",
    "nicotine_mg_per_ml": "Nicotine strength in mg/mL parsed from product text.",
    "nicotine_mg_per_pouch": "Nicotine amount per pouch parsed from product text.",
    "nicotine_pct": "Nicotine percentage parsed from product text.",
    "puff_count": "Advertised capacity parsed from product text first. For non-liquid vapes only, a structured puffs value above 200 through 200,000 is a fallback; 200 is treated as a source placeholder.",
    "thumbnail_url": "Product image URL.",
    "source_term": "First query that surfaced the de-duplicated product.",
    "source_terms": "All queries that surfaced the product, in collection order and pipe-separated.",
    "source_url": "Country search endpoint used for the request.",
    "scrape_timestamp": "UTC collection timestamp.",
}
STORE_DEFINITIONS = {
    "country_code": ITEM_DEFINITIONS["country_code"],
    "zone_slug": ITEM_DEFINITIONS["zone_slug"],
    "store_id": ITEM_DEFINITIONS["store_id"],
    "store_type": ITEM_DEFINITIONS["store_type"],
    "store_name": ITEM_DEFINITIONS["store_name"],
    "parent_store_type": ITEM_DEFINITIONS["parent_store_type"],
    "n_tobacco_observations": "Number of exported product observations for this location/store.",
    "product_types": "Distinct exported product types, pipe-separated.",
}
LOCATION_DEFINITIONS = {
    **{column: ITEM_DEFINITIONS[column] for column in LOCATION_COLS
       if column in ITEM_DEFINITIONS},
    "n_tobacco_observations": "Number of exported store-product observations at this location.",
}
DATA_DICTIONARY = [
    *(('items', column, ITEM_DEFINITIONS[column]) for column in ITEM_COLS),
    *(('stores', column, STORE_DEFINITIONS[column]) for column in STORE_COLS),
    *(('locations', column, LOCATION_DEFINITIONS[column]) for column in LOCATION_COLS),
]

def _attribute_puff_count(value) -> int | None:
    """Read a credible non-placeholder puff count from Rappi attributes."""
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        raw = parsed.get("puffs") if isinstance(parsed, dict) else None
        count = int(str(raw).strip())
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    # The saved feeds use 200 as a placeholder on unrelated liquids, pods and
    # devices, including products whose titles advertise much larger counts.
    # An explicit ``200 Puffs`` title is still retained by the name parser.
    return count if 200 < count <= 200_000 else None


def _pack_format_total(value) -> int | None:
    """Return the explicit total from Rappi formats such as ``10 x 18 Und``."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"\s*(\d{1,3})\s*[x×]\s*(\d{1,3})\s*"
        r"(?:u|un|und|unds|uds|unidades?)\.?\s*",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    outer, inner = int(match.group(1)), int(match.group(2))
    total = outer * inner
    return total if 2 <= total <= 1000 else None


def _heated_carton_total(value) -> int | None:
    """Normalize an explicit TEREA/HEETS carton count to individual sticks."""
    if not isinstance(value, str):
        return None
    heated_identity = re.search(r"\b(?:terea|heets)\b", value, re.IGNORECASE)
    reviewed_scarlet = (re.search(r"\bscarlet\b", value, re.IGNORECASE)
                         and re.search(r"\biluma\b", value, re.IGNORECASE))
    if not (heated_identity or reviewed_scarlet):
        return None
    cartons = re.search(r"(?<!\d)(\d{1,2})\s*cajetillas?\b", value, re.IGNORECASE)
    if not cartons:
        cartons = re.match(
            r"\s*(\d{1,2})\s*[x×]\s*cart[oó]n\b", value, re.IGNORECASE)
    if not cartons:
        return None
    count = int(cartons.group(1))
    total = count * 20
    return total if 2 <= count <= 50 and total <= 1000 else None


def _heated_single_pack_total(value) -> int | None:
    """Return the standard stick count for an explicit single TEREA/HEETS cajetilla."""
    if not isinstance(value, str) or "+" in value:
        return None
    if not re.search(r"\b(?:terea|heets)\b", value, re.IGNORECASE):
        return None
    if not re.search(r"\bcajetilla\b", value, re.IGNORECASE):
        return None
    if re.search(r"\bcajetillas\b|\bcart[oó]n\b|\bpaquete\b", value, re.IGNORECASE):
        return None
    return 20


def _reviewed_cigarette_carton_total(value, ean=None) -> int | None:
    """Return a verified total for a carton whose Rappi unit metadata is incomplete."""
    if not isinstance(value, str):
        return None
    blue_carton = re.fullmatch(
        r"\s*l\s*&\s*m\s+blue\s*x\s*10\s+cigarrillos?\s+cart[oó]n\s*",
        value,
        flags=re.IGNORECASE,
    )
    if blue_carton:
        return 100
    media_blue = re.fullmatch(
        r"\s*l\s*&\s*m\s+cigarrillo\s+cart[oó]n\s+media\s+blue\s*"
        r"\+\s*18\s+10\s+und\s*",
        value,
        flags=re.IGNORECASE,
    )
    if media_blue and str(ean or "").strip() == "7702005702417":
        return 100
    atomic = re.fullmatch(
        r"\s*cigarrillo\s+cart[oó]n\s+lucky\s+strike\s+atomic\s+10\s*[\'’´]?s\s*",
        value,
        flags=re.IGNORECASE,
    )
    return 10 if atomic else None


def _append_flag(value, flag: str) -> str:
    """Append one pipe-delimited review flag without duplicating existing flags."""
    flags = [part for part in str(value or "").split("|") if part]
    if flag not in flags:
        flags.append(flag)
    return "|".join(flags)


def _latest(directory: Path, pattern: str) -> Path:
    files = sorted(glob.glob(str(directory / pattern)))
    if not files:
        raise FileNotFoundError(f"no {pattern} in {directory}")
    return Path(files[-1])


def _configured_brand(name, source_brand, study_category,
                      brand_terms: list[dict]) -> tuple[str | None, str | None]:
    text = " ".join(part for part in (_normalize(name), _normalize(source_brand)) if part)
    candidates = [
        (variant, entry)
        for entry in brand_terms
        if entry["category"] == study_category
        for variant in brand_variants(entry)
    ]
    for variant, entry in sorted(candidates, key=lambda pair: len(_normalize(pair[0])), reverse=True):
        if _matches(text, _normalize(variant)):
            return str(entry["brand"]), str(entry["market_scope"])
    return None, None


# Bundle detection is component-based. A flavour conjunction (``Blueberry y Mint``), the
# ampersand inside a brand, or a context-required collision brand cannot establish a second
# family by itself. Multi-category brands (WAKA/Glucloud) are excluded at the canonical-brand
# level so a category-specific alias cannot leak back in.
_BUNDLE_PLUS_SEPARATOR_RE = re.compile(r"\s*\+\s*")
_BUNDLE_AMBIGUOUS_SEPARATOR_RE = re.compile(r"\s+&\s+|\s+y\s+", re.IGNORECASE)
_BUNDLE_HEADER_RE = re.compile(r"\bcombo\b", re.IGNORECASE)
_BUNDLE_ECIG_RE = re.compile(
    r"\b(?:cigarrillos? electronicos?|e cigarettes?|vape|vapes|vaper|vapers|"
    r"vapeador|vapeadores|pod|pods|e ?liquids?|liquido)\b|"
    r"\d[\d .]*\s*(?:k\s*)?(?:puffs?|pufs?|aspiraciones?|caladas?)\b|"
    r"\b\d{1,3}\s*k\b")
_BUNDLE_POUCH_RE = re.compile(
    r"\b(?:nicotine|nic) pouches?\b|\bpouches?\b|"
    r"bols(?:a|as|ita|itas) de nicotina")
_BUNDLE_HEATED_RE = re.compile(r"\b(?:terea|heets|iqos|iluma|heatsticks?)\b")
_BUNDLE_CIGARETTE_RE = re.compile(r"\b(?:cigarrillos?|cigarros?)\b")
_BUNDLE_ELECTRONIC_CIGARETTE_RE = re.compile(
    r"\bcigarrillos? electronicos?\b|\belectronic[oa]s? cigarrillos?\b")
_BUNDLE_CONTEXT_CORROBORATORS = {
    "electronic_cigarettes": _BUNDLE_ECIG_RE,
    "nicotine_pouches": re.compile(
        r"\b\d+(?:[.,]\d+)?\s*mg\b|\bnicotin|\bpouches?\b"),
    "heated_tobacco": _BUNDLE_HEATED_RE,
    "cigarettes": re.compile(r"\b(?:cigarrillos?|cigarros?|cajetillas?)\b"),
}


def _single_category_brand_variants(brand_terms: list[dict]) -> dict[str, dict[str, str]]:
    """Return bundle-safe brand variants with category and configured match mode.

    Category uniqueness is decided by canonical brand before aliases are expanded. This keeps
    every alias of a cross-category brand out of bundle inference.
    """
    canonical_categories: dict[str, set[str]] = {}
    for entry in brand_terms:
        canonical = _normalize(entry["brand"])
        canonical_categories.setdefault(canonical, set()).add(entry["category"])

    variants: dict[str, list[tuple[str, str]]] = {}
    for entry in brand_terms:
        canonical = _normalize(entry["brand"])
        if len(canonical_categories[canonical]) != 1:
            continue
        for variant in brand_variants(entry):
            normalized = _normalize(variant)
            if normalized:
                variants.setdefault(normalized, []).append(
                    (entry["category"], entry["match"]))

    result: dict[str, dict[str, str]] = {}
    for variant, matches in variants.items():
        categories = {category for category, _ in matches}
        if len(categories) != 1:
            continue
        result[variant] = {
            "category": next(iter(categories)),
            "match": ("distinctive" if any(mode == "distinctive" for _, mode in matches)
                      else "context_required"),
        }
    return result


def _bundle_component_families(
        component, brand_variants_by_family: dict[str, dict[str, str]], *,
        allow_brand_only: bool = True) -> set[str]:
    """Return families evidenced within one delimited title component."""
    text = _normalize(str(component or ""))
    if not text:
        return set()

    families: set[str] = set()
    if _BUNDLE_ECIG_RE.search(text):
        families.add("electronic_cigarettes")
    if _BUNDLE_POUCH_RE.search(text):
        families.add("nicotine_pouches")
    if _BUNDLE_HEATED_RE.search(text):
        families.add("heated_tobacco")
    if (_BUNDLE_CIGARETTE_RE.search(text)
            and not _BUNDLE_ELECTRONIC_CIGARETTE_RE.search(text)
            and "heated_tobacco" not in families):
        families.add("cigarettes")

    explicit_families = set(families)
    for variant, metadata in brand_variants_by_family.items():
        if not _matches(text, variant):
            continue
        category = metadata["category"]
        corroborated = bool(_BUNDLE_CONTEXT_CORROBORATORS[category].search(text))
        if (category == "cigarettes"
                and (_BUNDLE_ELECTRONIC_CIGARETTE_RE.search(text)
                     or "heated_tobacco" in explicit_families)):
            corroborated = False
        if (category in explicit_families or corroborated
                or (allow_brand_only and metadata["match"] == "distinctive"
                    and not explicit_families)):
            families.add(category)
    return families


def _bundle_families(
        name, brand_variants_by_family: dict[str, dict[str, str]]) -> set[str]:
    """Return independently evidenced families only for a real bundle structure."""
    raw = str(name or "")
    if "+" in raw:
        components = [part for part in _BUNDLE_PLUS_SEPARATOR_RE.split(raw) if part.strip()]
        allow_brand_only = True
    elif _BUNDLE_AMBIGUOUS_SEPARATOR_RE.search(raw):
        components = [part for part in _BUNDLE_AMBIGUOUS_SEPARATOR_RE.split(raw)
                      if part.strip()]
        # ``y`` commonly joins flavours, while spaced ``&`` occurs inside brand names.
        # Each side therefore needs explicit or category-corroborating product evidence.
        allow_brand_only = False
    else:
        components = []
        allow_brand_only = True
    if len(components) >= 2:
        evidence = [
            _bundle_component_families(
                part, brand_variants_by_family, allow_brand_only=allow_brand_only)
            for part in components
        ]
        nonempty = [families for families in evidence if families]
        if len(nonempty) < 2:
            return set()
        return set().union(*nonempty)
    if _BUNDLE_HEADER_RE.search(raw):
        return _bundle_component_families(raw, brand_variants_by_family)
    return set()


def _is_two_vape_gift_bundle(
        name, brand_variants_by_family: dict[str, dict[str, str]]) -> bool:
    """Require a proved vape component on both sides of a gift-offer plus sign."""
    raw = str(name or "")
    if "de regalo" not in _normalize(raw) or "+" not in raw:
        return False
    components = [part for part in _BUNDLE_PLUS_SEPARATOR_RE.split(raw) if part.strip()]
    vape_components = sum(
        "electronic_cigarettes" in _bundle_component_families(
            part, brand_variants_by_family)
        for part in components
    )
    return vape_components >= 2


def _xlsx_safe_frame(frame):
    """Escape spreadsheet formula prefixes in merchant-controlled text for XLSX only."""
    def safe(value):
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    return frame.apply(lambda column: column.map(safe))


def _format_workbook(path: Path) -> None:
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    workbook = load_workbook(path)
    header_fill = PatternFill("solid", fgColor="E7E6E6")
    header_font = Font(name="Aptos", size=10, color="222222", bold=True)
    header_border = Border(bottom=Side(style="thin", color="A6A6A6"))
    numeric_formats = {
        "latitude": "0.000000",
        "longitude": "0.000000",
        "price_local": "#,##0.00",
        "original_price_local": "#,##0.00",
        "discount_amount_local": "#,##0.00",
        "discount_pct": "0.00%",
        "unit_price_local": "#,##0.00",
        "volume_ml": "#,##0.##",
        "pack_count": "#,##0.##",
        "quantity": "#,##0.##",
        "stock": "#,##0.##",
        "nicotine_mg_per_ml": "#,##0.##",
        "nicotine_mg_per_pouch": "#,##0.##",
        "nicotine_pct": "0.##",
        "puff_count": "#,##0",
        "n_tobacco_observations": "#,##0",
    }
    preferred_widths = {
        "address": 38,
        "name": 44,
        "rationale": 42,
        "flags": 36,
        "source_terms": 42,
        "source_url": 42,
        "thumbnail_url": 42,
    }

    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        sheet.sheet_view.showGridLines = True
        sheet.row_dimensions[1].height = 24
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.border = header_border
            cell.alignment = Alignment(vertical="center", wrap_text=True)

        headers = {cell.column: str(cell.value or "") for cell in sheet[1]}
        for column_index, header in headers.items():
            if header in numeric_formats:
                for row_index in range(2, sheet.max_row + 1):
                    sheet.cell(row=row_index, column=column_index).number_format = (
                        numeric_formats[header]
                    )

        for column in sheet.iter_cols():
            header = str(column[0].value or "")
            width = max((len(str(cell.value)) for cell in column[:200]
                         if cell.value is not None), default=8)
            width = preferred_widths.get(header, min(max(width + 2, 10), 32))
            sheet.column_dimensions[column[0].column_letter].width = width

    summary = workbook["summary"]
    summary.column_dimensions["A"].width = 34
    summary.column_dimensions["B"].width = 22
    dictionary = workbook["data_dictionary"]
    dictionary.column_dimensions["A"].width = 16
    dictionary.column_dimensions["B"].width = 30
    dictionary.column_dimensions["C"].width = 88
    for cell in dictionary["C"][1:]:
        cell.alignment = Alignment(vertical="top", wrap_text=True)
    workbook.active = workbook.sheetnames.index("summary")
    workbook.save(path)


def _load_zone(country: str, zone: dict, data_root: Path, profile: dict,
               raw_path: str | Path | None = None,
               classification_path: str | Path | None = None):
    import pandas as pd

    slug = zone["slug"]
    raw_path = (Path(raw_path) if raw_path else
                _latest(data_root / country / "raw" / slug, "search_items_*.csv"))
    classification_path = (Path(classification_path) if classification_path else
                           data_root / country / "processed" / slug / "classifications.csv")
    if not raw_path.is_file():
        raise FileNotFoundError(f"search items not found for {slug}: {raw_path}")
    if not classification_path.exists():
        raise FileNotFoundError(f"classifications not found for {slug}: {classification_path}")
    raw = pd.read_csv(raw_path, dtype=str, keep_default_na=False)
    classified = pd.read_csv(classification_path, dtype=str, keep_default_na=False)
    keys = ["store_id", "product_id"]
    for label, frame in (("search", raw), ("classification", classified)):
        missing = set(keys) - set(frame.columns)
        if missing:
            raise ValueError(f"{slug}: {label} file lacks {sorted(missing)}")
        if frame.duplicated(keys).any():
            raise ValueError(f"{slug}: duplicate {label} product keys")
    missing_classification = set(CLASSIFICATION_COLS) - set(classified.columns)
    if missing_classification:
        raise ValueError(f"{slug}: classifications lack {sorted(missing_classification)}")
    raw_keys = set(map(tuple, raw[keys].astype(str).to_numpy()))
    classified_keys = set(map(tuple, classified[keys].astype(str).to_numpy()))
    if raw_keys != classified_keys:
        raise ValueError(
            f"{slug}: classification keys do not match the selected search file "
            f"({len(raw_keys - classified_keys)} missing, "
            f"{len(classified_keys - raw_keys)} extra)"
        )
    raw = raw.drop(columns=[column for column in CLASSIFICATION_COLS if column in raw.columns])
    frame = raw.merge(classified[keys + CLASSIFICATION_COLS], on=keys, how="inner",
                      validate="one_to_one")
    frame = frame[frame["primary_class"] == "tobacco"].copy()
    frame["study_category"] = frame["product_type"].map(STUDY_PRODUCT_TYPES)
    frame = frame[frame["study_category"].notna()].copy()
    frame["country_code"] = country
    frame["country"] = profile["name"]
    frame["city"] = profile["city"]
    frame["currency"] = profile["currency"]
    frame["zone_slug"] = slug
    frame["address"] = zone["address"]
    frame["district"] = zone["district"]
    frame["latitude"] = zone["lat"]
    frame["longitude"] = zone["lng"]
    return frame


def _artifact_token(run_token: str | None) -> str:
    token = (datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
             if run_token is None else str(run_token))
    if not _ARTIFACT_TOKEN_RE.fullmatch(token):
        raise ValueError(
            "run_token must use YYYYMMDD_HHMMSS_microseconds format"
        )
    return token


def run_export(country: str, addresses: list[str] | None = None, out_dir: str | None = None,
               data_root: str | Path | None = None, config_dir: str | Path | None = None,
               sources: dict[str, str | Path] | None = None,
               classification_paths: dict[str, str | Path] | None = None,
               run_token: str | None = None) -> dict:
    import pandas as pd

    artifact_token = _artifact_token(run_token)
    config_dir = Path(config_dir) if config_dir else STUDY_CONFIG
    data_root = Path(data_root) if data_root else ROOT / "data"
    profile = load_study_profile(country, config_dir)
    by_slug = {zone["slug"]: zone for zone in profile["zones"]}
    slugs = addresses or list(by_slug)
    if len(slugs) != len(set(slugs)):
        raise ValueError("duplicate addresses are not allowed")
    unknown = set(slugs) - set(by_slug)
    if unknown:
        raise ValueError(f"unknown {country} addresses: {sorted(unknown)}")
    for label, mapping in (("sources", sources), ("classification_paths", classification_paths)):
        if mapping is not None and set(mapping) != set(slugs):
            raise ValueError(f"{label} must contain exactly the selected address slugs")
    frames = [_load_zone(
        country, by_slug[slug], data_root, profile,
        raw_path=sources.get(slug) if sources else None,
        classification_path=(classification_paths.get(slug)
                             if classification_paths else None),
    ) for slug in slugs]
    items = pd.concat(frames, ignore_index=True)
    if items.empty:
        raise ValueError(f"{country}: no products in the four configured categories to export")

    enrichment = pd.DataFrame([
        enrich_tobacco_fields(row.get("name"), row.get("short_description"),
                              row.get("product_type"))
        for row in items.to_dict(orient="records")
    ], index=items.index)
    for column in ("nicotine_mg_per_ml", "nicotine_mg_per_pouch", "nicotine_pct", "puff_count"):
        items[column] = enrichment[column]
    source_pack = pd.to_numeric(items.get("pack_count"), errors="coerce")
    name_pack = pd.to_numeric(enrichment["pack_count"], errors="coerce")
    trusted_pack = source_pack.where(source_pack > 1)
    items["pack_count"] = trusted_pack.where(trusted_pack.notna(), name_pack)
    cigarette_family = items["product_type"].eq("cigarette")
    heated_family = items["product_type"].eq("heated_tobacco")
    stick_family = cigarette_family | heated_family
    pouch_family = items["product_type"].eq("nicotine_pouch")
    plausible_cigarette_counts = source_pack.isin({10, 12, 14, 15, 16, 18, 20, 24, 25, 30})
    items.loc[cigarette_family & name_pack.notna(), "pack_count"] = name_pack[
            cigarette_family & name_pack.notna()]
    items.loc[(heated_family | pouch_family) & name_pack.notna(), "pack_count"] = name_pack[
        (heated_family | pouch_family) & name_pack.notna()]
    items.loc[cigarette_family & name_pack.isna() & ~plausible_cigarette_counts,
              "pack_count"] = float("nan")
    vape_family = items["product_type"].isin(
        {"vape", "vape_disposable", "vape_pod", "vape_liquid"})
    items.loc[vape_family, "pack_count"] = name_pack[vape_family]
    parsed_puffs = pd.to_numeric(items["puff_count"], errors="coerce")
    attribute_values = (items["attributes_json"] if "attributes_json" in items
                        else pd.Series(None, index=items.index))
    attribute_puffs = pd.to_numeric(attribute_values.map(_attribute_puff_count), errors="coerce")
    items["puff_count"] = parsed_puffs
    missing_vape_puffs = (vape_family & ~items["product_type"].eq("vape_liquid")
                          & items["puff_count"].isna())
    items.loc[missing_vape_puffs, "puff_count"] = attribute_puffs[missing_vape_puffs]
    carton_name = items["name"].str.match(r"^\s*\d{1,2}\s*[x×]\s+", case=False, na=False)
    carton_count = stick_family & carton_name & name_pack.notna()
    items.loc[carton_count, "pack_count"] = name_pack[carton_count]
    leading_multiplier = pd.to_numeric(
        items["name"].str.extract(r"^\s*(\d{1,2})\s*[x×]\s+", expand=False),
        errors="coerce",
    )
    leading_source_total = (stick_family & carton_name & name_pack.isna()
                            & source_pack.between(10, 30))
    items.loc[leading_source_total, "pack_count"] = (
        leading_multiplier[leading_source_total] * source_pack[leading_source_total])
    carton_like = (
        stick_family
        & items["name"].str.contains(
            r"cart[oó]n|display|paquete.*cajetillas|con\s+\d+\s+cajetillas",
            case=False,
            regex=True,
            na=False,
        )
    )
    quantity_values = (items["quantity"] if "quantity" in items
                       else pd.Series(None, index=items.index))
    source_quantity = pd.to_numeric(quantity_values, errors="coerce")
    source_carton_total = carton_like & source_quantity.between(100, 1000)
    items.loc[source_carton_total, "pack_count"] = source_quantity[source_carton_total]
    ambiguous_carton = (carton_like & ~source_carton_total
                        & ~carton_count & ~leading_source_total)
    items.loc[ambiguous_carton, "pack_count"] = float("nan")
    pack_format_values = (items["pack_format_raw"] if "pack_format_raw" in items
                          else pd.Series("", index=items.index, dtype=object))
    pack_format_text = pack_format_values.fillna("").astype(str)
    pack_format_total = pd.to_numeric(
        pack_format_text.map(_pack_format_total), errors="coerce")
    heated_single_total = pd.to_numeric(
        items["name"].map(_heated_single_pack_total), errors="coerce")
    # A leading multiplier in the title describes the outer carton/bundle;
    # Rappi's pack format often describes only one inner pack (for example,
    # ``3 x Terea ...`` with ``1 x 20 Und``). Keep the title-derived total in
    # that case, while using exact source formats to recover unlabelled cartons.
    # ``1 x 10/20 Und`` frequently describes one inner pack even when the title
    # says carton. Do not let that source field undo the ambiguity guard. Exact
    # reviewed exceptions are applied below; true totals such as 10 x 18,
    # 20 x 10, and 1 x 200 remain usable.
    inner_pack_only = pack_format_text.str.match(
        r"^\s*1\s*[x×]\s*(?:10|12|14|15|16|18|20|24|25|30)\s*"
        r"(?:u|un|und|unds|uds|unidades?)\.?\s*$",
        case=False,
        na=False,
    )
    misleading_carton_format = ambiguous_carton & inner_pack_only
    conflicting_title_count = (inner_pack_only & name_pack.notna()
                               & pack_format_total.ne(name_pack))
    explicit_stick_total = (stick_family & pack_format_total.notna() & ~carton_name
                            & ~misleading_carton_format & ~conflicting_title_count
                            & heated_single_total.isna())
    items.loc[explicit_stick_total, "pack_count"] = pack_format_total[explicit_stick_total]
    reviewed_heated_single = heated_family & heated_single_total.notna()
    items.loc[reviewed_heated_single, "pack_count"] = heated_single_total[
        reviewed_heated_single]
    heated_carton_total = pd.to_numeric(
        items["name"].map(_heated_carton_total), errors="coerce")
    reviewed_heated_carton = heated_family & heated_carton_total.notna()
    items.loc[reviewed_heated_carton, "pack_count"] = heated_carton_total[
        reviewed_heated_carton]
    ean_values = (items["ean"] if "ean" in items
                  else pd.Series("", index=items.index))
    reviewed_cigarette_carton_total = pd.to_numeric([
        _reviewed_cigarette_carton_total(name, ean)
        for name, ean in zip(items["name"], ean_values)
    ], errors="coerce")
    reviewed_cigarette_carton_total = pd.Series(
        reviewed_cigarette_carton_total, index=items.index)
    reviewed_cigarette_carton = cigarette_family & reviewed_cigarette_carton_total.notna()
    items.loc[reviewed_cigarette_carton, "pack_count"] = reviewed_cigarette_carton_total[
        reviewed_cigarette_carton]
    additive_unit_bundle = (
        (heated_family | pouch_family)
        & items["name"].str.contains(
            r"\b\d+\s*(?:u|un|und|unidades?)\b.*\+.*"
            r"\b\d+\s*(?:u|un|und|unidades?)\b",
            case=False,
            regex=True,
            na=False,
        )
    )
    pouch_container_bundle = (
        pouch_family
        & items["name"].str.contains(
            r"^\s*\d+\s*[x×]\s*|\bpouches?\s+\d+\s*(?:u|un|und|unidades?)\b",
            case=False,
            regex=True,
            na=False,
        )
    )
    items.loc[additive_unit_bundle | pouch_container_bundle, "pack_count"] = float("nan")
    heated_welcome_kit = items["flags"].str.contains(
        r"(?:^|\|)study_heated_welcome_kit(?:\||$)", regex=True, na=False)
    items.loc[heated_welcome_kit, "pack_count"] = float("nan")

    names = items["name"].fillna("")
    single_category_brands = _single_category_brand_variants(profile["brand_terms"])
    cross_family_bundle = pd.Series(
        [len(_bundle_families(name, single_category_brands)) >= 2 for name in names],
        index=items.index,
    )
    gift_vape_bundle = pd.Series(
        [_is_two_vape_gift_bundle(name, single_category_brands) for name in names],
        index=items.index,
    )
    gift_vape_bundle &= vape_family
    mixed_bundle = cross_family_bundle | gift_vape_bundle
    for column in ("nicotine_mg_per_ml", "nicotine_mg_per_pouch", "nicotine_pct",
                   "puff_count", "pack_count"):
        items.loc[mixed_bundle, column] = float("nan")
    items.loc[mixed_bundle, "flags"] = items.loc[mixed_bundle, "flags"].map(
        lambda value: _append_flag(value, "mixed_bundle"))
    source_volume = pd.to_numeric(items.get("volume_ml"), errors="coerce")
    name_volume = pd.to_numeric(enrichment["volume_ml"], errors="coerce")
    items["volume_ml"] = source_volume.where(source_volume.notna(), name_volume)

    price = pd.to_numeric(items["price_local"], errors="coerce")
    original = pd.to_numeric(items["original_price_local"], errors="coerce")
    if price.isna().any() or (price <= 0).any():
        raise ValueError(f"{country}: price_local must be present and positive")
    discount = (original - price).where(original > price, 0).round(2)
    items["discount_amount_local"] = discount
    items["discount_pct"] = (discount / original).where(original > 0, 0).round(4)
    pack = pd.to_numeric(items["pack_count"], errors="coerce")
    items["unit_price_local"] = (price / pack).round(2).where(pack > 0)
    items["unit_price_unit"] = None
    items.loc[pack > 0, "unit_price_unit"] = "und"

    source_brand = items["brand"] if "brand" in items else pd.Series("", index=items.index)
    matched = pd.Series([
        _configured_brand(name, raw_brand, study_category, profile["brand_terms"])
        for name, raw_brand, study_category in zip(
            items["name"], source_brand, items["study_category"]
        )
    ], index=items.index)
    items["brand_market_scope"] = matched.map(lambda pair: pair[1])
    items["brand"] = [brand or raw or None for (brand, _), raw in zip(matched, source_brand)]
    for column in ITEM_COLS:
        if column not in items:
            items[column] = None
    items = items[ITEM_COLS].sort_values(["zone_slug", "store_name", "name"])

    stores = (items.groupby(["country_code", "zone_slug", "store_id"], dropna=False)
              .agg(store_type=("store_type", "first"), store_name=("store_name", "first"),
                   parent_store_type=("parent_store_type", "first"),
                   n_tobacco_observations=("product_id", "nunique"),
                   product_types=("product_type", lambda values: "|".join(sorted(set(values.dropna())))))
              .reset_index())
    stores = stores[STORE_COLS]
    locations = pd.DataFrame(profile["zones"])
    locations = locations[locations["slug"].isin(slugs)].copy()
    locations = locations.rename(columns={"slug": "zone_slug", "lat": "latitude",
                                          "lng": "longitude"})
    locations.insert(0, "currency", profile["currency"])
    locations.insert(0, "city", profile["city"])
    locations.insert(0, "country", profile["name"])
    locations.insert(0, "country_code", country)
    counts = items.groupby("zone_slug").size()
    locations["n_tobacco_observations"] = (
        locations["zone_slug"].map(counts).fillna(0).astype(int))
    locations = locations[LOCATION_COLS]
    summary_rows = [
        {"metric": "country_code", "value": country},
        {"metric": "currency", "value": profile["currency"]},
        {"metric": "locations", "value": len(slugs)},
        {"metric": "tobacco_observations", "value": len(items)},
        {"metric": "store_location_observations", "value": len(stores)},
    ]
    category_counts = items["study_category"].value_counts()
    summary_rows.extend(
        {"metric": f"products_{category}", "value": int(category_counts.get(category, 0))}
        for category in STUDY_CATEGORIES
    )
    summary = pd.DataFrame(summary_rows)
    dictionary = pd.DataFrame(DATA_DICTIONARY, columns=["sheet", "column", "definition"])

    destination = (Path(out_dir) if out_dir else
                   data_root / country / "processed" / (slugs[0] if len(slugs) == 1 else "combined"))
    destination.mkdir(parents=True, exist_ok=True)
    final = {
        "items_csv": destination / f"tobacco_items_{artifact_token}.csv",
        "stores_csv": destination / f"tobacco_stores_{artifact_token}.csv",
        "locations_csv": destination / f"locations_{artifact_token}.csv",
        "xlsx": destination / f"tobacco_master_{artifact_token}.xlsx",
    }
    reservation = destination / f".study_export_{artifact_token}.lock"
    try:
        with reservation.open("x", encoding="utf-8") as handle:
            handle.write(f"{artifact_token}\n")
    except FileExistsError as exc:
        raise FileExistsError(
            f"collection export token is already active: {artifact_token}"
        ) from exc

    stage_id = uuid.uuid4().hex
    work = {
        key: path.with_name(f".{path.stem}.{stage_id}.partial{path.suffix}")
        for key, path in final.items()
    }
    published: list[Path] = []
    try:
        conflicts = [path for path in final.values() if path.exists()]
        if conflicts:
            raise FileExistsError(
                "collection export targets already exist: "
                + ", ".join(str(path) for path in conflicts)
            )
        items.to_csv(work["items_csv"], index=False, encoding="utf-8-sig")
        stores.to_csv(work["stores_csv"], index=False, encoding="utf-8-sig")
        locations.to_csv(work["locations_csv"], index=False, encoding="utf-8-sig")
        with pd.ExcelWriter(work["xlsx"], engine="openpyxl") as writer:
            _xlsx_safe_frame(items).to_excel(writer, sheet_name="items", index=False)
            _xlsx_safe_frame(stores).to_excel(writer, sheet_name="stores", index=False)
            _xlsx_safe_frame(locations).to_excel(writer, sheet_name="locations", index=False)
            _xlsx_safe_frame(summary).to_excel(writer, sheet_name="summary", index=False)
            _xlsx_safe_frame(dictionary).to_excel(writer, sheet_name="data_dictionary", index=False)
        _format_workbook(work["xlsx"])
        # Recheck after the expensive workbook build. The token reservation serializes
        # cooperating exporters; this guard also refuses unrelated files created mid-run.
        conflicts = [path for path in final.values() if path.exists()]
        if conflicts:
            raise FileExistsError(
                "collection export targets appeared during staging: "
                + ", ".join(str(path) for path in conflicts)
            )
        for key, path in final.items():
            work[key].replace(path)
            published.append(path)
    except BaseException:
        # These paths were preflighted as absent and are reserved by this run, so removing
        # already-published members restores the all-or-none artifact-set invariant.
        for path in published:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        for path in work.values():
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            reservation.unlink(missing_ok=True)
        except OSError:
            pass
    return {**{key: str(path) for key, path in final.items()},
            "n_observations": len(items), "n_store_observations": len(stores)}
