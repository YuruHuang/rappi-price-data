"""Item pipelines: validation+regex, cross-type dedup, CSV writer (utf-8-sig)."""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

try:
    from scrapy.exceptions import DropItem
except ModuleNotFoundError:  # scrapy is only needed for the optional breadth crawl
    class DropItem(Exception):
        """Fallback so the search-first path can import this module without scrapy."""

from rappi_co.extract.regex_enrich import enrich_item
from rappi_co.items import MenuItem, Store

logger = logging.getLogger(__name__)


def _to_dict(item: Any) -> dict:
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return dict(item)


def _serialize_for_csv(value):
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


class ValidationPipeline:
    def process_item(self, item, spider):
        item_type = item.get("_item_type") if isinstance(item, dict) else None
        data = _to_dict(item)
        data.pop("_item_type", None)

        if item_type == "menu_item":
            data = enrich_item(data)
            try:
                validated = MenuItem.model_validate(data)
            except ValidationError as e:
                raise DropItem(f"MenuItem validation failed: {e}") from e
            out = validated.model_dump()
            out["_item_type"] = "menu_item"
            return out

        if item_type == "store":
            try:
                validated = Store.model_validate(data)
            except ValidationError as e:
                raise DropItem(f"Store validation failed: {e}") from e
            out = validated.model_dump()
            out["_item_type"] = "store"
            return out

        return item


class CrossTypeDedupPipeline:
    """Dedup stores by store_id (merging types/paths) and menu items by (store_id, product_id).

    Store rows are persisted in this pipeline (close_spider) rather than via
    CsvWriterPipeline because Scrapy closes pipelines in reverse priority
    order — CsvWriter (300) closes BEFORE this one (200), so we'd lose the
    merged dict otherwise.
    """

    STORE_COLUMNS = [
        "store_id", "slug", "name", "url", "vertical", "store_types", "address_text",
        "lat", "lng", "neighborhood", "district", "locality", "postal_code",
        "raw_store_info", "discovery_paths", "discovery_zones", "scrape_timestamp",
    ]

    def __init__(self):
        self._stores: dict[str, dict] = {}
        self._menu_keys: set[tuple[str, str]] = set()

    def open_spider(self, spider):
        from rappi_co import settings as S
        self._raw_dir = Path(S.DATA_RAW_DIR)
        self._raw_dir.mkdir(parents=True, exist_ok=True)
        self._ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._active_zone = getattr(S, "ACTIVE_ZONE_SLUG", "calle-19-centro")

    def process_item(self, item, spider):
        if not isinstance(item, dict):
            return item
        itype = item.get("_item_type")
        if itype == "store":
            sid = item["store_id"]
            existing = self._stores.get(sid)
            if existing is None:
                self._stores[sid] = item
                # Drop here too; stores are written in close_spider from the merged version.
                raise DropItem(f"Store {sid} captured (will be flushed at close)")
            merged = dict(existing)
            for key in ("store_types", "discovery_paths", "discovery_zones"):
                a = list(merged.get(key) or [])
                b = list(item.get(key) or [])
                merged[key] = list(dict.fromkeys(a + b))
            for key in ("address_text", "lat", "lng", "neighborhood", "district",
                        "locality", "postal_code", "raw_store_info"):
                if not merged.get(key) and item.get(key):
                    merged[key] = item[key]
            # `vertical` is scalar: first non-empty wins; flag cross-vertical
            # collisions so we know if the same store_id is being claimed by
            # both /tiendas and /restaurantes (shouldn't happen but defend).
            existing_v = merged.get("vertical")
            new_v = item.get("vertical")
            if not existing_v and new_v:
                merged["vertical"] = new_v
            elif existing_v and new_v and existing_v != new_v:
                logger.warning(
                    "vertical collision on store_id=%s: %r vs %r — keeping %r",
                    sid, existing_v, new_v, existing_v,
                )
            self._stores[sid] = merged
            raise DropItem(f"Store {sid} merged with prior record")

        if itype == "menu_item":
            key = (item["store_id"], item["product_id"])
            if key in self._menu_keys:
                raise DropItem(f"Duplicate menu item {key}")
            self._menu_keys.add(key)
            return item
        return item

    def close_spider(self, spider):
        rows = list(self._stores.values())
        if not rows:
            return
        # Suffix output with active zone so multi-zone runs don't overwrite each other.
        suffix = f"_{self._active_zone}" if self._active_zone else ""
        path = self._raw_dir / f"stores{suffix}_{self._ts}.csv"
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=self.STORE_COLUMNS, extrasaction="ignore")
            w.writeheader()
            for row in rows:
                w.writerow({c: _serialize_for_csv(row.get(c)) for c in self.STORE_COLUMNS})
        logger.info("wrote %d stores (zone=%s) to %s",
                    len(rows), self._active_zone, path)


class CsvWriterPipeline:
    STORE_COLUMNS = [
        "store_id", "slug", "name", "url", "vertical", "store_types", "address_text",
        "lat", "lng", "neighborhood", "district", "locality", "postal_code",
        "raw_store_info", "discovery_paths", "discovery_zones", "scrape_timestamp",
    ]
    MENU_COLUMNS = [
        "product_id", "master_product_id", "store_id", "name", "brand",
        "price_cop", "original_price_cop", "discount_pct", "unit_price_cop",
        "unit_price_unit", "volume_ml", "pack_count", "pack_format_raw",
        "menu_section", "menu_subsection", "category_id", "thumbnail_url",
        "short_description", "availability", "age_restriction", "has_antismoking",
        "stock", "quantity", "min_purchasing_units", "sale_type", "is_medical_product",
        "identification_required", "store_brand_name", "retail_id", "supplier",
        "has_menthol", "attributes_json",
        "abv_pct_from_text", "abv_evidence", "sugar_g_from_text", "sugar_evidence",
        "source_url", "scrape_timestamp",
    ]

    def __init__(self):
        self._store_rows: list[dict] = []
        self._menu_count: int = 0
        self._raw_dir: Path | None = None
        self._ts: str | None = None
        self._menu_path: Path | None = None
        self._menu_file = None
        self._menu_writer = None

    def open_spider(self, spider):
        from rappi_co import settings as S
        self._raw_dir = Path(S.DATA_RAW_DIR)
        self._raw_dir.mkdir(parents=True, exist_ok=True)
        self._ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        # Stream menu rows directly to disk so a forced shutdown doesn't lose
        # the buffered items (previously they were held in memory until close).
        self._menu_path = self._raw_dir / f"menu_items_{self._ts}.csv"
        self._menu_file = open(self._menu_path, "w", encoding="utf-8-sig", newline="")
        self._menu_writer = csv.DictWriter(
            self._menu_file, fieldnames=self.MENU_COLUMNS, extrasaction="ignore"
        )
        self._menu_writer.writeheader()
        self._menu_file.flush()

    def process_item(self, item, spider):
        if not isinstance(item, dict):
            return item
        itype = item.get("_item_type")
        if itype == "menu_item" and self._menu_writer is not None:
            self._menu_writer.writerow(
                {c: _serialize_for_csv(item.get(c)) for c in self.MENU_COLUMNS}
            )
            self._menu_count += 1
            # Flush every 100 rows so a kill -9 loses at most ~100 items.
            if self._menu_count % 100 == 0:
                self._menu_file.flush()
        return item

    def close_spider(self, spider):
        # Stores still flush at close (CrossTypeDedupPipeline owns the merged dict).
        merged = getattr(spider, "_merged_stores", [])
        if merged:
            self._store_rows.extend(merged)
        if self._store_rows:
            path = self._raw_dir / f"stores_{self._ts}.csv"
            self._write_csv(path, self.STORE_COLUMNS, self._store_rows)
            logger.info("wrote %d stores to %s", len(self._store_rows), path)
        if self._menu_file is not None:
            try:
                self._menu_file.flush()
                self._menu_file.close()
            except (OSError, ValueError) as e:
                logger.warning("failed to flush/close menu file %s: %s", self._menu_path, e)
            logger.info("wrote %d menu items to %s", self._menu_count, self._menu_path)

    @staticmethod
    def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            w.writeheader()
            for row in rows:
                w.writerow({c: _serialize_for_csv(row.get(c)) for c in columns})
