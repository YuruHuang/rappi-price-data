"""Catalog content-API helpers: tobacco-aisle detection + row mapping (no network)."""
from rappi_co.parsers.catalog_api import TOBACCO_AISLE_RE, catalog_product_to_row


def test_tobacco_aisle_regex_matches_real_aisle_names():
    for name in ("Cigarrillos y vaporizadores", "Cigarrillos, tabaco y riesgo reducido",
                 "Vaporizadores y dispositivos", "Nicotina"):
        assert TOBACCO_AISLE_RE.search(name), name
    for name in ("Fruver", "Lácteos y huevos", "Licores y cervezas", "Snacks y Pasabocas"):
        assert not TOBACCO_AISLE_RE.search(name), name


def test_catalog_product_to_row_maps_to_menu_schema():
    prod = {"product_id": "2093395947", "name": "Marlboro Gold Cigarrillo x20",
            "price": 11200, "real_price": 12500, "category_name": "Cigarrillos",
            "ean": "7702", "quantity": 20, "unit_type": "und", "presentation": "1 x 20 Und"}
    meta = {"store_id": "900139848", "store_type": "turbo",
            "parent_store_type": "turbo_home", "store_name": "Turbo"}
    row = catalog_product_to_row(prod, meta, "catalog?store=900139848")

    assert row is not None
    assert row["store_id"] == "900139848" and row["product_id"] == "2093395947"
    assert row["name"] == "Marlboro Gold Cigarrillo x20"
    assert row["menu_section"] == "Cigarrillos"
    assert row["price_cop"] == 11200
    assert row["store_type"] == "turbo" and row["parent_store_type"] == "turbo_home"
    assert row["source"] == "catalog" and row["source_term"] == "catalog"


def test_catalog_product_to_row_skips_storeless_product():
    assert catalog_product_to_row({"product_id": "1", "name": "x", "price": 1}, {}, "u") is None
