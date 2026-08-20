"""Build the CO tobacco master deliverable (multi-sheet XLSX + CSVs).

Joins the classifier output with the raw menu fields (price, discount, EAN, size,
supplier, regulatory signals, store info), regex-enriches nicotine/puff/pack, derives
brand and a trustworthy per-unit price, and writes a master workbook that links stores
and menu items. Multiple addresses retain separate location-specific observations.

  * tobacco_master_<ts>.xlsx
      - items:             every in-scope tobacco product, all attributes, store link
      - stores:            location/store dimension, linked by (zone_slug, store_id)
      - paraphernalia_oos: captured out-of-scope items, retained rather than dropped
      - review_candidates: uncertain rows retained for manual recall review
      - locations:         the configured delivery-location dimension
      - summary:           counts and per-type price stats
      - data_dictionary:   column definitions, units, and caveats
  * tobacco_items_<ts>.csv:   the items sheet, flat
  * tobacco_stores_<ts>.csv:  the stores sheet, flat

Prices are Colombian pesos (COP), whole-peso values.

  # one address
  python -m rappi_co.export.tobacco_deliverable --address calle-19-centro

  # combine multiple addresses without collapsing location-specific observations
  python -m rappi_co.export.tobacco_deliverable --address calle-19-centro --address carrera-108-fontibon
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from rappi_co.enrich.tobacco_fields import enrich_tobacco_fields

ROOT = Path(__file__).resolve().parent.parent.parent
logger = logging.getLogger(__name__)

# Raw menu (search_items) columns carried onto each item. Excludes columns already
# present in the classifier output (store_type, name, brand, menu_section, ...) to
# avoid merge collisions.
COMMERCE = [
    "master_product_id", "ean", "category_id", "retail_id",
    "price_cop", "original_price_cop", "discount_pct",
    "unit_price_cop", "unit_price_unit",
    "volume_ml", "pack_count", "quantity", "min_purchasing_units", "sale_type", "pack_format_raw",
    "availability", "stock", "age_restriction", "alcoholic_beverage", "has_antismoking",
    "has_menthol", "is_medical_product", "identification_required",
    "requires_medical_prescription",
    "store_name", "parent_store_type", "supplier",
    "thumbnail_url", "attributes_json", "short_description", "source_term", "source_url",
    "scrape_timestamp",
]

# Full, ordered column set for the location-specific item observations sheet.
ITEM_COLS = [
    # location provenance
    "zone_slug", "address", "district", "latitude", "longitude", "zone_slugs", "n_zones",
    # identity + store link
    "product_id", "master_product_id", "retail_id", "store_id", "store_type", "store_name",
    "parent_store_type",
    # product
    "name", "brand", "ean", "supplier", "menu_section", "menu_subsection", "category_id",
    # price (COP)
    "price_cop", "original_price_cop", "discount_pct", "discount_amount_cop",
    "unit_price_cop", "unit_price_unit",
    # size / pack
    "volume_ml", "pack_count", "quantity", "min_purchasing_units", "sale_type", "pack_format_raw",
    # regulatory / availability signals
    "availability", "stock", "age_restriction", "alcoholic_beverage", "has_antismoking",
    "has_health_warning", "has_menthol", "is_medical_product", "identification_required",
    "requires_medical_prescription",
    # classification
    "primary_class", "product_type", "confidence", "method", "rationale", "flags",
    # tobacco enrichment
    "nicotine_mg_per_ml", "nicotine_mg_per_pouch", "nicotine_pct", "nicotine_source", "puff_count",
    # provenance
    "thumbnail_url", "attributes_json", "source_term", "source_url", "scrape_timestamp",
]

STORE_COLS = [
    "zone_slug", "address", "district", "latitude", "longitude",
    "store_id", "store_type", "store_name", "parent_store_type",
    "zone_slugs", "n_tobacco_products", "product_types",
]

# Column definitions shipped as a data_dictionary sheet.
DATA_DICTIONARY = [
    ("zone_slug", "Delivery-location slug for this price and availability observation."),
    ("address", "Delivery street address configured for this observation."),
    ("district", "Bogota district for the configured delivery location."),
    ("latitude", "Configured delivery latitude in decimal degrees (WGS84)."),
    ("longitude", "Configured delivery longitude in decimal degrees (WGS84)."),
    ("zone_slugs", "Delivery address(es) whose search surfaced this row, '|'-joined."),
    ("n_zones", "Number of addresses that surfaced this (store, product)."),
    ("product_id", "Rappi product id (unique per store; reused across a chain's stores)."),
    ("master_product_id", "Rappi master-catalog id (shared across stores)."),
    ("retail_id", "Retailer's own product id."),
    ("store_id", "Rappi store id; combine with zone_slug to link to the `stores` sheet."),
    ("store_type", "Rappi store-type slug."),
    ("store_name", "Store display name."),
    ("parent_store_type", "Rappi parent store-type category."),
    ("name", "Product name as shown on Rappi."),
    ("brand", "Brand parsed from the name via the tobacco lexicon (source feed has no brand field)."),
    ("ean", "Barcode (GTIN) when Rappi provides it; ~60% coverage, lower for vapes."),
    ("supplier", "Supplier/importer from the product attributes when present."),
    ("menu_section", "Aisle / catalog section."),
    ("menu_subsection", "Catalog subsection when supplied by Rappi."),
    ("category_id", "Rappi category identifier, preserved as text."),
    ("price_cop", "Current price in Colombian pesos (whole pesos)."),
    ("original_price_cop", "Pre-discount price in COP."),
    ("discount_pct", "Effective discount = (original-price)/original, 0-1 (derived, not raw)."),
    ("discount_amount_cop", "original_price_cop - price_cop, floored at 0."),
    ("unit_price_cop", "Per-unit price in COP = round(price_cop / pack_count); for cigarettes this is price-per-stick. Derived, not Rappi's raw value."),
    ("unit_price_unit", "Unit for unit_price_cop ('und' = per stick/unit)."),
    ("volume_ml", "Millilitres (e-liquids) parsed from name/presentation; empty for most tobacco."),
    ("pack_count", "Units per pack (e.g. 20 for a cigarette pack); from quantity or name."),
    ("quantity", "Raw Rappi quantity field."),
    ("min_purchasing_units", "Minimum purchasable units reported by Rappi."),
    ("sale_type", "Rappi sale type ('U' = per unit)."),
    ("pack_format_raw", "Raw pack/presentation string from Rappi."),
    ("availability", "in_stock / out_of_stock."),
    ("stock", "Reported stock level when available."),
    ("age_restriction", "Rappi age-restriction flag (18+); set only when Rappi tags the product, so some age-restricted items read blank (source signal, not inferred)."),
    ("has_antismoking", "Rappi anti-smoking/health-warning flag."),
    ("has_health_warning", "Alias of has_antismoking (Rappi's health-warning signal)."),
    ("has_menthol", "Menthol flag from product attributes; present only when Rappi supplies the attribute."),
    ("is_medical_product", "Rappi medical-product flag."),
    ("alcoholic_beverage", "Rappi alcoholic-beverage flag."),
    ("identification_required", "Whether Rappi reports an ID requirement."),
    ("requires_medical_prescription", "Rappi prescription-required flag."),
    ("primary_class", "Classifier verdict: tobacco (in scope) or out_of_scope."),
    ("product_type", "cigarette / vape / vape_pod / vape_disposable / vape_liquid / heated_tobacco / nicotine_pouch / cigar / pipe_tobacco / rolling_tobacco / shisha_tobacco / nrt."),
    ("confidence", "Classifier confidence: high / medium / low."),
    ("method", "Classifier rule that fired (keyword_strong, keyword_generic, ...)."),
    ("rationale", "Short deterministic explanation of the classification rule."),
    ("flags", "Classifier flags, '|'-joined."),
    ("nicotine_mg_per_ml", "Nicotine strength (mg/mL) parsed from the name; populated only when the name states it, which is uncommon on Rappi (a source limitation)."),
    ("nicotine_mg_per_pouch", "Nicotine amount per pouch (mg/pouch) parsed from the name; sparse for the same reason."),
    ("nicotine_pct", "Nicotine strength (%) parsed from the name; sparse for the same reason."),
    ("nicotine_source", "Text field from which nicotine strength was parsed."),
    ("puff_count", "Puff count parsed from the name (disposable vapes)."),
    ("thumbnail_url", "Product image URL."),
    ("attributes_json", "Additional source attributes serialized as JSON when present."),
    ("source_term", "Search term that surfaced the product."),
    ("source_url", "Search endpoint reference."),
    ("scrape_timestamp", "UTC timestamp of collection."),
    ("CAVEATS", "brand is name-derived; source fields can be empty. Nicotine strength and menthol/age flags come straight from Rappi and are sparse (names rarely state mg/mL), so treat blanks as unknown, not zero. Rows are location-specific observations. Use price_cop for pack price and unit_price_cop for per-stick."),
]

_BRANDS = None


# Product-type / descriptor words that live in the lexicon but are NOT brands.
_NON_BRAND = {
    "vape", "vapes", "vapeador", "vapeadores", "vaporizador", "vaporizadores", "vapeo",
    "e cig", "e cigarette", "e liquid", "vape juice", "nicotina liquida", "liquido para vape",
    "liquido para vapeo", "eliquido", "nic salt", "nic salts", "sal de nic", "sal de nicotina",
    "sales de nicotina", "puff descartable", "snus", "nicotine pouch", "nicotine pouches",
    "bolsita de nicotina", "bolsitas de nicotina", "sticks de tabaco", "heatsticks",
    "melaza para shisha", "melaza para narguile", "cajetilla de cigarrillos", "habano", "habanos",
    "blunt",
}


def _brand_list():
    """Distinctive brand tokens from the lexicon (drops generic tobacco and type words)."""
    global _BRANDS
    if _BRANDS is None:
        from rappi_co.classify.tobacco_classifier import load_lexicon, _normalize
        lex = load_lexicon()
        generic = {_normalize(g) for g in (lex.get("tobacco_generic") or [])}
        cand = (lex.get("tobacco_safe") or []) + (lex.get("tobacco_context_required") or [])
        brands = []
        for b in cand:
            nb = _normalize(b)
            if (nb and nb not in generic and nb not in _NON_BRAND
                    and not nb.startswith("tabaco") and not nb.startswith("cigarr")
                    and not nb.startswith("cigaril") and not nb.startswith("cigarit")):
                brands.append(nb)
        _BRANDS = sorted(set(brands), key=len, reverse=True)  # longest first
    return _BRANDS


def _brand_from_name(name):
    from rappi_co.classify.tobacco_classifier import _normalize, _matches
    t = _normalize(name)
    if not t:
        return None
    for b in _brand_list():
        if _matches(t, b):
            return b.title()
    return None


def _latest(pattern: str) -> str | None:
    cands = sorted(glob.glob(pattern))
    return cands[-1] if cands else None


def _menu_source_for(slug: str) -> str | None:
    """Per-address commerce source: the search+breadth union when it exists, else search only.

    `collect.union` writes menu_items_unified_*.csv when the breadth crawl has been folded in; the
    classifier runs over the same file, so preferring it here keeps the classify/export merge aligned.
    """
    raw = ROOT / "data" / "raw" / slug
    return _latest(str(raw / "menu_items_unified_*.csv")) or _latest(str(raw / "search_items_*.csv"))


def _split_flags(s):
    if isinstance(s, list):
        return s
    try:
        import pandas as pd
        if pd.isna(s):
            return []
    except (TypeError, ValueError):
        pass
    return [x for x in str(s or "").split("|") if x]


def _zone_metadata(slug: str) -> dict:
    """Validated, publishable location metadata from config/zones_co.yml."""
    if not slug:
        return {"zone_slug": "", "address": "", "district": "",
                "latitude": None, "longitude": None}
    zones = (yaml.safe_load((ROOT / "config" / "zones_co.yml").read_text(encoding="utf-8"))
             or {}).get("zones") or []
    for zone in zones:
        if zone.get("slug") == slug:
            return {
                "zone_slug": slug,
                "address": zone.get("address") or "",
                "district": zone.get("district") or "",
                "latitude": float(zone["lat"]),
                "longitude": float(zone["lng"]),
            }
    raise ValueError(f"unknown zone slug: {slug!r}")


def _load_one(classifications_path: str, menu_path: str | None, zone_slug: str):
    """Load one address and preserve identifier columns exactly as source text."""
    import pandas as pd
    if not menu_path or not Path(menu_path).exists():
        raise FileNotFoundError(f"menu/search input not found for {zone_slug}: {menu_path}")
    df = pd.read_csv(classifications_path, dtype=str, keep_default_na=False)
    df["flags"] = df["flags"].apply(_split_flags)
    menu = pd.read_csv(menu_path, dtype=str, keep_default_na=False)
    keep = ["product_id", "store_id"] + [c for c in COMMERCE if c in menu.columns]
    menu = menu[keep].drop_duplicates(["store_id", "product_id"])
    df = df.merge(menu, on=["store_id", "product_id"], how="left", validate="one_to_one",
                  indicator=True)
    missing = df["_merge"] != "both"
    if missing.any():
        raise ValueError(
            f"{zone_slug}: {int(missing.sum())} classified rows have no matching source row"
        )
    df = df.drop(columns="_merge")
    for key, value in _zone_metadata(zone_slug).items():
        df[key] = value
    return df


def _dedup_zones(df):
    """Keep location observations distinct while recording cross-location availability."""
    import pandas as pd
    if df.empty:
        df = df.copy()
        df["zone_slugs"] = pd.Series(dtype="object")
        df["n_zones"] = pd.Series(dtype="int64")
        return df
    observation_key = ["zone_slug", "store_id", "product_id"]
    product_key = ["store_id", "product_id"]

    def _zset(s):
        return sorted({str(x) for x in s if str(x) and str(x) != "nan"})

    out = df.drop_duplicates(subset=observation_key, keep="first").copy()
    out["zone_slugs"] = out.groupby(product_key)["zone_slug"].transform(
        lambda s: "|".join(_zset(s)))
    out["n_zones"] = out.groupby(product_key)["zone_slug"].transform(
        lambda s: len(_zset(s)))
    return out


def _validate_items(items, expected_zones: set[str]) -> None:
    """Fail the export before publication when release invariants are violated."""
    import pandas as pd

    if items.empty:
        raise ValueError("export contains no in-scope tobacco observations")
    observed = set(items["zone_slug"].dropna().astype(str)) - {""}
    if expected_zones and observed != expected_zones:
        raise ValueError(
            f"location coverage mismatch: expected {sorted(expected_zones)}, got {sorted(observed)}"
        )
    required = ["store_id", "product_id", "name", "price_cop", "product_type"]
    for col in required:
        blank = items[col].isna() | items[col].astype(str).str.strip().isin({"", "nan"})
        if blank.any():
            raise ValueError(f"{int(blank.sum())} tobacco observations have blank {col}")
    price = pd.to_numeric(items["price_cop"], errors="coerce")
    if price.isna().any() or (price <= 0).any():
        raise ValueError("price_cop must be present and positive on every tobacco observation")
    if items.duplicated(["zone_slug", "store_id", "product_id"]).any():
        raise ValueError("duplicate (zone_slug, store_id, product_id) observations")
    for col in ("ean", "category_id"):
        values = items[col].fillna("").astype(str).str.strip()
        corrupt = values.str.endswith(".0")
        if corrupt.any():
            raise ValueError(f"{col} contains float-corrupted identifiers")
    flags = items["flags"].fillna("").astype(str).str.strip().str.lower()
    if flags.eq("nan").any():
        raise ValueError("flags contains literal 'nan' values")


def _style_workbook(workbook) -> None:
    """Apply compact, consistent workbook usability settings."""
    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.table import Table, TableStyleInfo

    workbook.properties.title = "Rappi Colombia tobacco observations"
    workbook.properties.subject = "Two-location tobacco availability and pricing dataset"
    workbook.properties.creator = "Rappi Colombia data pipeline"
    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    for index, ws in enumerate(workbook.worksheets, 1):
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
        for column in ws.columns:
            letter = column[0].column_letter
            width = max((len(str(c.value)) for c in column[:200] if c.value is not None), default=8)
            ws.column_dimensions[letter].width = min(max(width + 2, 10), 42)
        if ws.max_row > 1 and ws.max_column > 0:
            table = Table(displayName=f"DatasetTable{index}", ref=ws.dimensions)
            table.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium2", showFirstColumn=False, showLastColumn=False,
                showRowStripes=True, showColumnStripes=False,
            )
            ws.add_table(table)


def run_export(addresses: list[str] | None = None, out_dir: str | None = None,
               classifications_path: str | None = None, menu_path: str | None = None) -> dict:
    import pandas as pd

    # Resolve the (zone_slug, classifications, menu) sources.
    sources: list[tuple[str, str, str | None]] = []
    if addresses:
        if len(addresses) != len(set(addresses)):
            raise ValueError("duplicate --address values are not allowed")
        single = len(addresses) == 1
        for slug in addresses:
            cpath = (classifications_path if single and classifications_path
                     else _latest(str(ROOT / "data" / "co" / "processed" / slug / "classifications*.csv")))
            mpath = (menu_path if single and menu_path
                     else _menu_source_for(slug))
            sources.append((slug, cpath, mpath))
    else:
        if not classifications_path:
            classifications_path = _latest(str(ROOT / "data" / "co" / "processed" / "classifications_*.csv"))
        if not classifications_path:
            raise FileNotFoundError("no classifications CSV found")
        sources.append(("", classifications_path, menu_path))

    frames = []
    for slug, cpath, mpath in sources:
        if not cpath or not Path(cpath).exists():
            raise FileNotFoundError(f"classifications not found for {slug or '<single>'}: {cpath}")
        frames.append(_load_one(cpath, mpath, slug))
    if not frames:
        raise FileNotFoundError("no classifications found for the requested addresses")
    df = pd.concat(frames, ignore_index=True)

    def _numcol(name):
        return (pd.to_numeric(df[name], errors="coerce") if name in df.columns
                else pd.Series(float("nan"), index=df.index, dtype="float64"))

    # Effective discount from the price gap (Rappi's raw discount field is unreliable).
    op = _numcol("original_price_cop")
    pr = _numcol("price_cop")
    amt = (op - pr).where(op > pr, 0)
    df["discount_amount_cop"] = amt
    df["discount_pct"] = (amt / op).where(op > 0, 0).round(4)

    # Regex enrichment (nicotine/puff + pack/volume from the name).
    if df.empty:
        for c in ("nicotine_mg_per_ml", "nicotine_mg_per_pouch", "nicotine_pct",
                  "nicotine_source", "puff_count",
                  "pack_count", "volume_ml"):
            if c not in df.columns:
                df[c] = None
    else:
        enr = df.apply(lambda r: enrich_tobacco_fields(r.get("name"), r.get("short_description")),
                       axis=1, result_type="expand")
        for c in ["nicotine_mg_per_ml", "nicotine_mg_per_pouch", "nicotine_pct",
                  "nicotine_source", "puff_count"]:
            df[c] = enr[c]
        # Pack size: trust the source pack only when it is a genuine multi-unit count (>1).
        # A source pack of 1 means "one unit/pack" and says nothing about sticks-per-pack,
        # so prefer the name-parsed count (e.g. "20 Und"); if the name has none, leave it
        # unknown rather than a wrong 1 (which would corrupt price-per-stick).
        src_pack = _numcol("pack_count")
        name_pack = pd.to_numeric(enr["pack_count"], errors="coerce")
        trusted = src_pack.where(src_pack > 1)
        # Rappi sometimes puts inventory-like values (for example 100) in quantity
        # for a single vape device. Vape-family pack counts are therefore accepted
        # only when the product name explicitly states the count (x2, x4 pods, etc.).
        product_type = df["product_type"].fillna("").astype(str)
        vape_family = product_type.isin({"vape", "vape_disposable", "vape_pod", "vape_liquid"})
        df["pack_count"] = trusted.where(trusted.notna(), name_pack)
        df.loc[vape_family, "pack_count"] = name_pack[vape_family]
        vol_src = _numcol("volume_ml")
        df["volume_ml"] = vol_src.where(vol_src.notna(), pd.to_numeric(enr["volume_ml"], errors="coerce"))

    # Derive a trustworthy per-unit price (Rappi's raw unit_price is intermittently x100-scaled):
    # unit_price_cop = round(price_cop / pack_count) for count-based products.
    pack = _numcol("pack_count")
    df["unit_price_cop"] = (pr / pack).round(0).where(pack > 0)
    df["unit_price_unit"] = df["unit_price_unit"] if "unit_price_unit" in df.columns else None
    df.loc[pack > 0, "unit_price_unit"] = "und"

    # Derive brand from the name (the search feed has no product-brand field).
    df["brand"] = df["name"].apply(_brand_from_name) if not df.empty else None
    # has_health_warning is Rappi's anti-smoking/health-warning signal.
    df["has_health_warning"] = df["has_antismoking"] if "has_antismoking" in df.columns else None

    # In-scope tobacco + captured paraphernalia, each deduplicated across zones.
    tob = _dedup_zones(df[df["primary_class"] == "tobacco"].copy())
    para = _dedup_zones(df[df["flags"].apply(lambda fs: "tobacco_paraphernalia" in fs)].copy())
    review = _dedup_zones(df[df["flags"].apply(
        lambda fs: any(flag.startswith(("oos_section_", "oos_context_", "oos_has_"))
                       for flag in fs)
    )].copy())

    for frame in (tob, para, review):
        frame["flags"] = frame["flags"].apply(lambda f: "|".join(f) if isinstance(f, list) else (f or ""))
        for c in ITEM_COLS:
            if c not in frame.columns:
                frame[c] = None

    tob = tob.sort_values(["store_type", "store_name", "name"], na_position="last")
    items = tob[ITEM_COLS]
    _validate_items(items, expected_zones=set(addresses or []))
    stores = _stores_sheet(tob)
    locations = _locations_sheet(items)

    if out_dir:
        out_dir_p = Path(out_dir)
    elif addresses and len(addresses) == 1:
        out_dir_p = ROOT / "data" / "co" / "processed" / addresses[0]
    elif addresses:
        out_dir_p = ROOT / "data" / "co" / "processed" / "combined"
    else:
        out_dir_p = ROOT / "data" / "co" / "processed"
    out_dir_p.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    items_csv = out_dir_p / f"tobacco_items_{ts}.csv"
    stores_csv = out_dir_p / f"tobacco_stores_{ts}.csv"
    xlsx_path = out_dir_p / f"tobacco_master_{ts}.xlsx"
    items_work = out_dir_p / f"tobacco_items_{ts}.tmp.csv"
    stores_work = out_dir_p / f"tobacco_stores_{ts}.tmp.csv"
    xlsx_work = out_dir_p / f"tobacco_master_{ts}.tmp.xlsx"

    items.to_csv(items_work, index=False, encoding="utf-8-sig")
    stores.to_csv(stores_work, index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(xlsx_work, engine="openpyxl") as xl:
        items.to_excel(xl, sheet_name="items", index=False)
        stores.to_excel(xl, sheet_name="stores", index=False)
        para[ITEM_COLS].to_excel(xl, sheet_name="paraphernalia_oos", index=False)
        review[ITEM_COLS].to_excel(xl, sheet_name="review_candidates", index=False)
        locations.to_excel(xl, sheet_name="locations", index=False)
        _summary(items, stores).to_excel(xl, sheet_name="summary", index=False)
        pd.DataFrame(DATA_DICTIONARY, columns=["column", "definition"]).to_excel(
            xl, sheet_name="data_dictionary", index=False)
        _style_workbook(xl.book)
    items_work.replace(items_csv)
    stores_work.replace(stores_csv)
    xlsx_work.replace(xlsx_path)

    logger.info("tobacco items: %d across %d stores | zones: %s | paraphernalia: %d",
                len(items), len(stores), ",".join(s for s, _, _ in sources if s) or "single", len(para))
    logger.info("wrote %s", xlsx_path)
    return {"xlsx": str(xlsx_path),
            "items_csv": str(items_csv), "stores_csv": str(stores_csv),
            "n_items": len(items), "n_stores": len(stores), "n_paraphernalia": len(para),
            "n_review_candidates": len(review),
            "n_locations": len(locations),
            "zones": [s for s, _, _ in sources if s],
            "product_type_counts": items["product_type"].value_counts(dropna=False).to_dict()}


def _stores_sheet(tob):
    """One row per location/store, linked to items by (zone_slug, store_id)."""
    import pandas as pd
    if tob.empty:
        return pd.DataFrame(columns=STORE_COLS)
    key = ["zone_slug", "store_id"]
    g = tob.groupby(key, dropna=False)
    rows = g.agg(
        address=("address", "first"),
        district=("district", "first"),
        latitude=("latitude", "first"),
        longitude=("longitude", "first"),
        store_type=("store_type", "first"),
        store_name=("store_name", "first"),
        parent_store_type=("parent_store_type", "first"),
        n_tobacco_products=("product_id", "nunique"),
    ).reset_index()
    ptypes = (g["product_type"]
              .apply(lambda s: "|".join(sorted({str(x) for x in s.dropna() if str(x) != "nan"})))
              .rename("product_types").reset_index())
    zones = (g["zone_slugs"]
             .apply(lambda s: "|".join(sorted({z for v in s.dropna()
                                               for z in str(v).split("|") if z})))
             .rename("zone_slugs").reset_index())
    rows = rows.merge(ptypes, on=key, how="left").merge(zones, on=key, how="left")
    return rows[STORE_COLS].sort_values("n_tobacco_products", ascending=False)


def _locations_sheet(items):
    """One row per configured delivery location represented in the output."""
    columns = ["zone_slug", "address", "district", "latitude", "longitude",
               "n_tobacco_observations", "n_store_observations"]
    if items.empty:
        return items.iloc[:0].reindex(columns=columns)
    rows = (items.groupby(["zone_slug", "address", "district", "latitude", "longitude"],
                          dropna=False)
            .agg(n_tobacco_observations=("product_id", "size"),
                 n_store_observations=("store_id", "nunique"))
            .reset_index())
    return rows[columns].sort_values("zone_slug")


def _summary(items, stores):
    import pandas as pd
    price = pd.to_numeric(items["price_cop"], errors="coerce")
    unit = pd.to_numeric(items["unit_price_cop"], errors="coerce")
    disc = pd.to_numeric(items["discount_amount_cop"], errors="coerce").fillna(0)
    rows = [
        {"metric": "tobacco_items", "value": len(items)},
        {"metric": "stores_with_tobacco", "value": len(stores)},
        {"metric": "items_on_discount", "value": int((disc > 0).sum())},
        {"metric": "overall_median_price_cop", "value": float(price.median()) if price.notna().any() else 0},
    ]
    for z, v in items["zone_slug"].value_counts(dropna=False).items():
        if str(z):
            rows.append({"metric": f"zone:{z}", "value": int(v)})
    # Per-product-type price stats (mixing types in one median is not interpretable).
    for pt, sub in items.groupby(items["product_type"].fillna("(none)")):
        p = pd.to_numeric(sub["price_cop"], errors="coerce")
        u = pd.to_numeric(sub["unit_price_cop"], errors="coerce")
        rows.append({"metric": f"count:{pt}", "value": int(len(sub))})
        rows.append({"metric": f"median_price_cop:{pt}",
                     "value": float(p.median()) if p.notna().any() else 0})
        if pt == "cigarette":
            rows.append({"metric": "median_price_per_stick_cop:cigarette",
                         "value": float(u.median()) if u.notna().any() else 0})
    for flag in ("nrt", "zero_nicotine", "context_confirmed:section"):
        rows.append({"metric": f"flag:{flag}",
                     "value": int(items["flags"].astype(str).str.contains(flag, regex=False).sum())})
    return pd.DataFrame(rows)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--address", action="append",
                   help="zone slug (repeatable); auto-locates its classifications + search_items")
    p.add_argument("--classifications", default=None)
    p.add_argument("--menu", default=None)
    p.add_argument("--out", default=None)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    res = run_export(addresses=args.address, out_dir=args.out,
                     classifications_path=args.classifications, menu_path=args.menu)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
