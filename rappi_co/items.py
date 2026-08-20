"""Pydantic data schemas. Single source of truth for the dim/fact tables."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Store(BaseModel):
    """One row per unique storefront (cross-type dedup applied)."""

    store_id: str
    slug: str
    name: str
    url: str
    vertical: Optional[str] = None  # "retail" | "restaurant"
    store_types: list[str] = Field(default_factory=list)
    address_text: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    neighborhood: Optional[str] = None
    district: Optional[str] = None
    locality: Optional[str] = None
    postal_code: Optional[str] = None
    raw_store_info: Optional[str] = None
    discovery_paths: list[str] = Field(default_factory=list)
    discovery_zones: list[str] = Field(default_factory=list)
    scrape_timestamp: datetime = Field(default_factory=_utcnow)


class MenuItem(BaseModel):
    """One row per (store, product) on a listing or aisle page."""

    product_id: str
    master_product_id: Optional[str] = None
    store_id: str
    name: str
    brand: Optional[str] = None
    price_cop: Optional[float] = None
    original_price_cop: Optional[float] = None
    discount_pct: Optional[float] = None
    unit_price_cop: Optional[float] = None
    unit_price_unit: Optional[str] = None
    volume_ml: Optional[float] = None
    pack_count: Optional[int] = None
    pack_format_raw: Optional[str] = None
    menu_section: Optional[str] = None
    menu_subsection: Optional[str] = None
    category_id: Optional[str] = None
    thumbnail_url: Optional[str] = None
    short_description: Optional[str] = None
    availability: str = "in_stock"
    age_restriction: Optional[bool] = None
    has_antismoking: Optional[bool] = None
    stock: Optional[int] = None
    quantity: Optional[float] = None
    min_purchasing_units: Optional[int] = None
    sale_type: Optional[str] = None
    is_medical_product: Optional[bool] = None
    identification_required: Optional[bool] = None
    store_brand_name: Optional[str] = None
    retail_id: Optional[str] = None
    supplier: Optional[str] = None
    has_menthol: Optional[bool] = None
    attributes_json: Optional[str] = None
    abv_pct_from_text: Optional[float] = None
    abv_evidence: Optional[str] = None
    sugar_g_from_text: Optional[float] = None
    sugar_evidence: Optional[str] = None
    source_url: str
    scrape_timestamp: datetime = Field(default_factory=_utcnow)


class Classification(BaseModel):
    product_id: str
    store_id: str
    primary_class: str
    confidence: str = "medium"
    method: str = "keyword"
    rationale: Optional[str] = None
    flags: list[str] = Field(default_factory=list)
    classifier_version: str = "v1"
    scrape_timestamp: datetime = Field(default_factory=_utcnow)
