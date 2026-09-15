"""Lossless beverage replay of archived, completed search collections.

The original tobacco CSV remains unchanged. This reader links an exact CSV to its
completion manifest and raw responses, and reparses the raw evidence so beverage
units, descriptions, attributes, and uncertainty survive the first pass.
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import re
from pathlib import Path
from typing import Any

from rappi_co.parsers.search_api import search_product_to_row, validate_search_payload


def _archived_path(parent: Path, name: str) -> Path:
    """A manifest can reference only files inside its own archive directory."""
    candidate = (parent / name).resolve()
    if not candidate.is_relative_to(parent.resolve()):
        raise ValueError(f"archive reference escapes its directory: {name!r}")
    if Path(name).name != name or (parent / name).is_symlink():
        raise ValueError(f"archive references must be direct files, without aliases or symlinks: {name!r}")
    return candidate


def _same_value(left: Any, right: Any, *, numeric: bool = False) -> bool:
    if str(left if left is not None else "") == str(right if right is not None else ""):
        return True
    if numeric:
        try:
            return float(left) == float(right)
        except (ValueError, TypeError):
            pass
    return False


def _bool(value: Any) -> bool | None:
    if value is True or value == 1:
        return True
    if value is False or value == 0:
        return False
    if isinstance(value, str):
        if value.strip().lower() in {"true", "1"}:
            return True
        if value.strip().lower() in {"false", "0"}:
            return False
    return None


def _availability(product: dict) -> str:
    available = _bool(product.get("is_available"))
    stocked = _bool(product.get("in_stock"))
    possible_stockout = any(_bool(product.get(key)) is True for key in (
        "is_possible_stockout", "possibly_out_of_stock"))
    if available is False or stocked is False:
        return "out_of_stock"
    if possible_stockout:
        return "possibly_out_of_stock"
    if available is True or stocked is True:
        return "in_stock"
    return "unknown"


def _observed_url(product: dict) -> str | None:
    for key in ("product_url", "url", "web_url", "permalink"):
        value = product.get(key)
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            return value
    return None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def replay_search(source: Path) -> tuple[list[dict], list[dict]]:
    """Return richer rows and per-query coverage for one exact search CSV.

    Missing, incomplete, mismatched, or unparseable archives fail closed. The
    first observed offer is preserved; later disagreements are explicit audit
    records. Search execution completeness does not establish catalog coverage.
    """
    source = Path(source)
    if source.is_symlink():
        raise ValueError("source CSV must not be a symlink")
    source = source.resolve()
    match = re.fullmatch(r"search_items_(\d{8}_\d{6})\.csv", source.name)
    if not match:
        raise ValueError("source must be an exact search_items_<timestamp>.csv")
    manifest_path = source.with_name(source.name.replace("search_items_", "search_manifest_", 1)).with_suffix(".json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("complete") is not True:
        raise ValueError("replay requires a complete search manifest")
    if manifest.get("items") != source.name:
        raise ValueError("search manifest references a different items CSV")
    queries = manifest.get("queries")
    results = manifest.get("term_results")
    if (not isinstance(queries, list) or not queries or
            any(not isinstance(q, str) or not q.strip() for q in queries) or
            len(set(queries)) != len(queries) or
            not isinstance(results, list) or len(results) != len(queries) or
            any(not isinstance(entry, dict) for entry in results) or
            [entry.get("query") for entry in results] != queries):
        raise ValueError("search manifest query and archive records do not match")
    if (isinstance(manifest.get("n_items"), bool) or not isinstance(manifest.get("n_items"), int)
            or manifest["n_items"] < 1):
        raise ValueError("search manifest must provide a positive integer item count")
    if "request_count" in manifest and (
            isinstance(manifest["request_count"], bool) or manifest["request_count"] != len(queries)):
        raise ValueError("search manifest request count does not match its queries")
    raw_directory = manifest.get("raw_directory")
    if not isinstance(raw_directory, str) or not raw_directory:
        raise ValueError("search manifest has no raw archive directory")
    raw_dir = _archived_path(source.parent, raw_directory)
    if raw_dir.name != f"search_raw_{match.group(1)}":
        raise ValueError("raw archive directory must belong to this exact source timestamp")
    currency = manifest.get("currency")
    if not isinstance(currency, str) or not currency:
        raise ValueError("search manifest must identify the currency")

    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not {"store_id", "product_id"}.issubset(reader.fieldnames):
            raise ValueError("source CSV is missing observation identity columns")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("source CSV contains duplicate columns")
        csv_rows = list(reader)
    if any(None in row or not row.get("store_id") or not row.get("product_id") for row in csv_rows):
        raise ValueError("source CSV has malformed rows or blank observation identities")
    for original in csv_rows:
        for field in ("country_code", "currency"):
            if field in manifest and field in original and original[field] != manifest[field]:
                raise ValueError(f"source CSV {field} disagrees with its manifest")
    baseline = {(row["store_id"], row["product_id"]): row for row in csv_rows}
    if len(baseline) != len(csv_rows):
        raise ValueError("source CSV contains duplicate observation keys")

    rows: dict[tuple[str, str], dict] = {}
    terms_by_key: dict[tuple[str, str], list[str]] = {}
    evidence_by_key: dict[tuple[str, str], list[str]] = {}
    conflicts_by_key: dict[tuple[str, str], list[dict]] = {}
    coverage: list[dict] = []
    used_raw_files: set[Path] = set()
    compare_fields = ("name", "master_product_id", "ean", "alcoholic_beverage", "price_local", "original_price_local", "availability",
                      "quantity", "unit_type", "presentation", "short_description",
                      "attributes_json", "product_url")
    for entry in results:
        term = entry["query"]
        raw_name = entry.get("raw_file")
        if not isinstance(raw_name, str) or not raw_name:
            raise ValueError(f"missing raw file for query {term!r}")
        raw_path = _archived_path(raw_dir, raw_name)
        if raw_path in used_raw_files:
            raise ValueError("multiple queries reference the same archived response")
        used_raw_files.add(raw_path)
        with gzip.open(raw_path, "rt", encoding="utf-8") as handle:
            payload = validate_search_payload(json.load(handle), term)
        group_sizes: list[int] = []
        raw_count = usable_count = new_count = 0
        for group in payload["stores"]:
            if not isinstance(group, dict):
                raise ValueError(f"query {term!r} contains a malformed store group")
            products = group.get("products") or []
            if not isinstance(products, list):
                raise ValueError(f"query {term!r} contains a malformed product list")
            group_sizes.append(len(products))
            raw_count += len(products)
            for product in products:
                if not isinstance(product, dict):
                    continue
                if (group.get("store_id") not in (None, "") and product.get("store_id") not in (None, "")
                        and str(group["store_id"]) != str(product["store_id"])):
                    raise ValueError(f"query {term!r} has conflicting store identity on a product")
                row = search_product_to_row(group, product, term, manifest.get("search_url") or "")
                if row is None:
                    continue
                csv_core = {"name": row.get("name"), "master_product_id": row.get("master_product_id"),
                            "price_local": row.get("price_cop"), "original_price_local": row.get("original_price_cop")}
                price = row.get("price_cop")
                original_price = row.get("original_price_cop")
                invalid_price = isinstance(product.get("price"), bool) or (price is not None and not math.isfinite(price))
                invalid_original = isinstance(product.get("real_price"), bool) or (original_price is not None and not math.isfinite(original_price))
                usable_count += 1
                key = (str(row["store_id"]), str(row["product_id"]))
                native_id = str(product.get("product_id") or product.get("id"))
                original = baseline.get(key, {})
                row.update({
                    **{field: original.get(field) for field in (
                        "country_code", "country", "city", "scrape_timestamp")},
                    "currency": currency,
                    "price_local": None if invalid_price else price,
                    "original_price_local": None if invalid_original else original_price,
                    "invalid_price_source": invalid_price,
                    "invalid_original_price_source": invalid_original,
                    "source_product_id": native_id,
                    "unit_type": product.get("unit_type"),
                    "quantity": product.get("quantity"),
                    "presentation": product.get("presentation"),
                    "short_description": str(product.get("description") or "").strip() or None,
                    "attributes_json": _json(product.get("attributes")) if product.get("attributes") is not None else None,
                    "source_product_json": _json(product),
                    "product_url": _observed_url(product),
                    "availability": _availability(product),
                    "is_available_raw": product.get("is_available"),
                    "in_stock_raw": product.get("in_stock"),
                    "is_possible_stockout_raw": product.get("is_possible_stockout"),
                    "source_manifest_path": str(manifest_path),
                })
                if currency != "COP":
                    row.update(price_cop=None, original_price_cop=None, unit_price_cop=None)
                terms_by_key.setdefault(key, [])
                if term not in terms_by_key[key]:
                    terms_by_key[key].append(term)
                evidence_by_key.setdefault(key, [])
                if str(raw_path) not in evidence_by_key[key]:
                    evidence_by_key[key].append(str(raw_path))
                if key in rows:
                    first = rows[key]
                    if first["source_product_id"] != native_id:
                        raise ValueError(f"normalized product key collision at {key!r}: "
                                         f"{first['source_product_id']!r} and {native_id!r}")
                    changed = {field: {"first": first.get(field), "later": row.get(field)}
                               for field in compare_fields if first.get(field) != row.get(field)}
                    if changed:
                        conflicts_by_key.setdefault(key, []).append({
                            "query": term, "raw_file": str(raw_path), "fields": changed})
                else:
                    for field in ("name", "master_product_id", "price_local", "original_price_local"):
                        if field in original and not _same_value(original[field], csv_core.get(field),
                                                                numeric=field.endswith("price_local")):
                            raise ValueError(f"first archived {field} differs from its exact source CSV at {key!r}")
                    if "short_description" in original and str(original["short_description"] or "") != str(row.get("short_description") or "")[:1000]:
                        raise ValueError(f"first archived description differs from its exact source CSV at {key!r}")
                    rows[key] = row
                    new_count += 1
        if "new_items" in entry and (isinstance(entry["new_items"], bool) or entry["new_items"] != new_count):
            raise ValueError(f"query {term!r} new-item count disagrees with its manifest")
        coverage.append({
            "query": term, "raw_file": str(raw_path),
            "raw_rows": raw_count, "usable_rows": usable_count,
            "new_items": new_count, "duplicate_rows": usable_count - new_count,
            "skipped_rows": raw_count - usable_count,
            "store_groups": len(group_sizes),
            "group_sizes_json": _json(group_sizes),
            "capped_store_groups": sum(size >= 25 for size in group_sizes),
            "max_group_products": max(group_sizes, default=0),
            "catalog_coverage_complete": False,
        })
    if rows.keys() != baseline.keys():
        raise ValueError("archived product keys do not match the exact source CSV")
    if manifest.get("n_items") != len(rows):
        raise ValueError("archived item count does not match the completion manifest")
    if {p.resolve() for p in raw_dir.glob("*.json.gz")} != used_raw_files:
        raise ValueError("raw archive files do not exactly match the manifest responses")
    for key, row in rows.items():
        row["source_terms"] = "|".join(terms_by_key[key])
        row["source_evidence_paths"] = "|".join(evidence_by_key[key])
        row["source_conflicts_json"] = _json(conflicts_by_key.get(key, []))
        row["source_conflict"] = bool(conflicts_by_key.get(key))
    return list(rows.values()), coverage
