"""Tests for the search/menu parsers: PUM unit-price, image URL, volume/pack, product row."""
import pytest

from rappi_co.parsers.store_payload import (
    _parse_pum, _full_image_url, _derive_volume, _product_to_row,
)


@pytest.mark.parametrize("pum,expected", [
    ("730/und", (730.0, "und")),          # no "$" prefix (the common CO form)
    ("$12.500/kg", (12500.0, "kg")),      # "$" + Colombian thousands separator
    ("$ 1.234 / L", (1234.0, "l")),
    ("", (None, None)),
    ("sin pum", (None, None)),
])
def test_parse_pum(pum, expected):
    assert _parse_pum(pum) == expected


@pytest.mark.parametrize("image,expected", [
    (None, None),
    (123, None),
    ("abc.png", "https://images.rappi.com.co/products/abc.png"),
    ("http://cdn/x.jpg", "http://cdn/x.jpg"),
])
def test_full_image_url(image, expected):
    assert _full_image_url(image) == expected


@pytest.mark.parametrize("pres,qty,unit,expected", [
    ("12x330 ml", None, "", (12, 330.0)),
    ("750ml", None, "", (1, 750.0)),
    ("1 X 10 Und", None, "", (None, None)),   # count units aren't a volume
])
def test_derive_volume(pres, qty, unit, expected):
    assert _derive_volume(pres, qty, unit) == expected


def test_product_row_pack_from_quantity_and_pum_and_image():
    prod = {
        "product_id": "p1", "name": "Cigarrillo X 10 Und", "price": 7000, "real_price": 7000,
        "quantity": 10, "unit_type": "und", "presentation": "1 X 10 Und",
        "pum": "700/und", "image": "img.png",
        "attributes": {"supplier": "Almacenes Test S.A.", "has_menthol": True},
    }
    row = _product_to_row(prod, "s1", "Cigarrillos", "u")
    assert row["pack_count"] == 10                      # from quantity (unit_type 'und')
    assert row["price_cop"] == 7000.0
    assert row["unit_price_cop"] == 700.0               # PUM "700/und" now parses
    assert row["thumbnail_url"] == "https://images.rappi.com.co/products/img.png"
    assert row["supplier"] == "Almacenes Test S.A."
    assert row["has_menthol"] is True
