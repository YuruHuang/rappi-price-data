"""Tests for name-based size enrichment and the multi-address dedup in the master export."""
import pytest

from rappi_co.enrich.tobacco_fields import enrich_tobacco_fields


@pytest.mark.parametrize("name,expected", [
    ("Marlboro Rojo Cigarrilos X10 Und", 10),
    ("Lucky Strike Cigarrillo Gin 20 Und", 20),
    ("L&M Cigarrillo Verde Rojo + 18 10 Und", 10),
    ("Cajetilla x20 Premium", 20),
    ("Vape Airfuze 30000 Puff Rainbow", None),   # puffs are not a pack count
])
def test_pack_count_from_name(name, expected):
    assert enrich_tobacco_fields(name)["pack_count"] == expected


@pytest.mark.parametrize("name,expected", [
    ("E-liquid Nic Salt 30ml Menta", 30.0),
    ("Esencia 60 mL Sandia", 60.0),
    ("Lucky Strike 20 Und", None),
])
def test_volume_ml_from_name(name, expected):
    assert enrich_tobacco_fields(name)["volume_ml"] == expected


def test_puff_count_still_works():
    assert enrich_tobacco_fields("Vape Airfuze 30000 Puff")["puff_count"] == 30000


@pytest.mark.parametrize("name,expected", [
    ("Vape 24,000 Puff", 24000),
    ("Vape 20.000 Puffs", 20000),
    ("Vape 15 K Puff", 15000),
    ("Vape 1.5K Puffs", 1500),
    ("Vape 000 Puff", None),
])
def test_puff_count_formatted_numbers(name, expected):
    assert enrich_tobacco_fields(name)["puff_count"] == expected


@pytest.mark.parametrize("name,expected", [
    ("Vuse Go 1000 Puf", 1000),
    ("Divi 10000 Aspiraciones", 10000),
])
def test_market_puff_spellings_are_study_only(name, expected):
    assert enrich_tobacco_fields(name)["puff_count"] is None
    assert enrich_tobacco_fields(name, product_type="vape_disposable")["puff_count"] == expected


def test_spaced_puff_count_is_not_mistaken_for_pack_x():
    row = enrich_tobacco_fields("Vape Pulse X 25 000 Puffs - Blue Razz Ice", product_type="vape")
    assert row["puff_count"] == 25000
    assert row["pack_count"] is None


def test_decimal_gram_weight_is_not_a_pack_count():
    row = enrich_tobacco_fields("Bagz Nic Pouches Mint 8mg X15.10gr",
                                product_type="nicotine_pouch")
    assert row["pack_count"] is None


@pytest.mark.parametrize("name,expected", [
    ("Vaper Ignite V150 Berry Blast 15k", 15000),
    ("Elfbar Ice King 40 K Doble Apple Ice", 40000),
])
def test_bare_k_puffs_require_vape_context(name, expected):
    assert enrich_tobacco_fields(name)["puff_count"] is None
    assert enrich_tobacco_fields(name, product_type="vape")["puff_count"] == expected


@pytest.mark.parametrize("name,expected", [
    ("Vaper Ijoy Captain 10000 Blue Razz", 10000),
    ("Vapeador Rams Bar 20.000 Pineapple", 20000),
    ("Vaper 40.000 Dojo Strawberry", 40000),
])
def test_bare_numeric_puffs_require_vape_product_context(name, expected):
    replacement = name.replace("Vaper", "Device").replace("Vapeador", "Device")
    assert enrich_tobacco_fields(replacement)["puff_count"] is None
    assert enrich_tobacco_fields(name, product_type="vape")["puff_count"] == expected
    assert enrich_tobacco_fields(replacement, product_type="vape")["puff_count"] == expected


@pytest.mark.parametrize("name,expected", [
    ("10 x Carton Marlboro Cigarrillo Gold Box 20", 200),
    ("10 x Carton Philip Morris Cigarrillo Blue Spin Box 12", 120),
])
def test_cigarette_carton_pack_count_uses_outer_and_inner_counts(name, expected):
    assert enrich_tobacco_fields(name)["pack_count"] is None
    assert enrich_tobacco_fields(name, product_type="cigarette")["pack_count"] == expected


@pytest.mark.parametrize("name,product_type,expected", [
    ("Cigarros Malboro Gold 3.5 Cajetilla 10u", "cigarette", 10),
    ("Cigarros Malboro Red 3.5 Cajetilla 20un", "cigarette", 20),
    ("Delicados Ovalados 18s", "cigarette", 18),
    ("Winston Red 20's", "cigarette", 20),
    ("Camel Tabaco Filters Original 25S", "cigarette", 25),
    ("VELO Green Spearmint 15 s", "nicotine_pouch", 15),
    ("Cigarrillos Bold X20u.", "cigarette", 20),
    ("Cigarrillo Cartón Lucky Strike Atomic 10´S", "cigarette", 10),
    ("Terea Amber Cajetilla X 20unds", "heated_tobacco", 20),
])
def test_market_pack_suffixes(name, product_type, expected):
    assert enrich_tobacco_fields(name, product_type=product_type)["pack_count"] == expected


def test_nicotine_units_are_product_specific():
    liquid = enrich_tobacco_fields("Nic salt 20mg/ml frutilla")
    pouch = enrich_tobacco_fields("VELO Bolsitas de Nicotina 8mg")
    assert liquid["nicotine_mg_per_ml"] == 20.0
    assert liquid["nicotine_mg_per_pouch"] is None
    assert pouch["nicotine_mg_per_ml"] is None
    assert pouch["nicotine_mg_per_pouch"] == 8.0


def test_product_type_routes_brandless_pouch_mg():
    row = enrich_tobacco_fields("Combo Mentolado y Frutal Cool Mint 6 mg",
                                product_type="nicotine_pouch")
    assert row["nicotine_mg_per_pouch"] == 6.0
    assert row["nicotine_mg_per_ml"] is None


def test_mg_per_gram_is_not_reported_as_mg_per_pouch():
    row = enrich_tobacco_fields("Kik Strong Mint (10 mg/g)", product_type="nicotine_pouch")
    assert row["nicotine_mg_per_pouch"] is None
    assert row["nicotine_mg_per_ml"] is None


def test_study_regex_expansions_do_not_change_legacy_calls():
    legacy_pack = enrich_tobacco_fields("Terea Amber 20 unds")
    study_pack = enrich_tobacco_fields("Terea Amber 20 unds", product_type="heated_tobacco")
    assert legacy_pack["pack_count"] is None
    assert study_pack["pack_count"] == 20

    legacy_puffs = enrich_tobacco_fields("Vape Pulse 25 000 Puffs")
    study_puffs = enrich_tobacco_fields("Vape Pulse 25 000 Puffs", product_type="vape")
    assert legacy_puffs["puff_count"] is None
    assert study_puffs["puff_count"] == 25000

    legacy_mg = enrich_tobacco_fields("Pouch Mint 10 mg/g")
    study_mg = enrich_tobacco_fields("Pouch Mint 10 mg/g", product_type="nicotine_pouch")
    assert legacy_mg["nicotine_mg_per_pouch"] == 10
    assert study_mg["nicotine_mg_per_pouch"] is None


def test_vape_product_type_supplies_nicotine_context_for_percent_strength():
    study = enrich_tobacco_fields(
        "Veev Now Watermelon 3.5%", product_type="vape_disposable")
    legacy = enrich_tobacco_fields("Veev Now Watermelon 3.5%")
    assert study["nicotine_pct"] == 3.5
    assert legacy["nicotine_pct"] is None


def test_dedup_zones_preserves_location_observations():
    pd = pytest.importorskip("pandas")
    from rappi_co.export.tobacco_deliverable import _dedup_zones
    # (s1, p1) appears in zones a and b; (s2, p9) only in a.
    df = pd.DataFrame({
        "store_id": ["s1", "s1", "s2"],
        "product_id": ["p1", "p1", "p9"],
        "zone_slug": ["a", "b", "a"],
        "price_cop": [100, 100, 200],
    })
    out = _dedup_zones(df)
    assert len(out) == 3
    overlap = out[(out.store_id == "s1") & (out.product_id == "p1")]
    assert set(overlap["zone_slug"]) == {"a", "b"}
    assert set(overlap["zone_slugs"]) == {"a|b"}
    assert set(overlap["n_zones"]) == {2}
    solo = out[(out.store_id == "s2") & (out.product_id == "p9")].iloc[0]
    assert solo["zone_slugs"] == "a"
    assert solo["n_zones"] == 1


def test_split_flags_treats_nan_as_empty():
    from rappi_co.export.tobacco_deliverable import _split_flags
    assert _split_flags(float("nan")) == []


def test_dedup_zones_empty():
    pd = pytest.importorskip("pandas")
    from rappi_co.export.tobacco_deliverable import _dedup_zones
    out = _dedup_zones(pd.DataFrame(columns=["store_id", "product_id", "zone_slug"]))
    assert len(out) == 0
    assert "zone_slugs" in out.columns and "n_zones" in out.columns


def _write(tmp_path, cls_rows, menu_rows):
    pd = pytest.importorskip("pandas")
    cpath, mpath = tmp_path / "classifications.csv", tmp_path / "menu.csv"
    pd.DataFrame(cls_rows).to_csv(cpath, index=False)
    pd.DataFrame(menu_rows).to_csv(mpath, index=False)
    return str(cpath), str(mpath)


def _cls(pid, sid, name, product_type="cigarette"):
    return {"product_id": pid, "store_id": sid, "store_type": "market", "name": name,
            "brand": "", "menu_section": "Cigarrillos", "menu_subsection": "",
            "primary_class": "tobacco", "product_type": product_type, "confidence": "high",
            "method": "keyword_strong", "rationale": "", "flags": ""}


def test_run_export_merge_is_store_specific(tmp_path):
    """The critical fix: the same product_id at two stores must keep each store's own price."""
    pd = pytest.importorskip("pandas")
    from rappi_co.export import tobacco_deliverable as tex
    cls = [_cls("P", "s1", "Marlboro Rojo 20 Und"), _cls("P", "s2", "Marlboro Rojo 20 Und")]
    menu = [
        {"product_id": "P", "store_id": "s1", "price_cop": 4900, "original_price_cop": 4900,
         "store_name": "Store One", "parent_store_type": "market"},
        {"product_id": "P", "store_id": "s2", "price_cop": 7000, "original_price_cop": 7000,
         "store_name": "Store Two", "parent_store_type": "market"},
    ]
    cpath, mpath = _write(tmp_path, cls, menu)
    res = tex.run_export(classifications_path=cpath, menu_path=mpath, out_dir=str(tmp_path))
    items = pd.read_csv(res["items_csv"])
    s1 = items[items.store_id.astype(str) == "s1"].iloc[0]
    s2 = items[items.store_id.astype(str) == "s2"].iloc[0]
    assert (s1["price_cop"], s1["store_name"]) == (4900, "Store One")   # not corrupted by s2
    assert (s2["price_cop"], s2["store_name"]) == (7000, "Store Two")
    assert s1["brand"] == "Marlboro"          # derived from name
    assert s1["pack_count"] == 20             # from name "20 Und"
    assert s1["unit_price_cop"] == 245        # 4900/20, derived (not Rappi's raw pum)


def test_run_export_discount(tmp_path):
    pd = pytest.importorskip("pandas")
    from rappi_co.export import tobacco_deliverable as tex
    cls = [_cls("P", "s1", "Lucky Strike 20 Und")]
    menu = [{"product_id": "P", "store_id": "s1", "price_cop": 4800, "original_price_cop": 6000,
             "store_name": "S"}]
    cpath, mpath = _write(tmp_path, cls, menu)
    res = tex.run_export(classifications_path=cpath, menu_path=mpath, out_dir=str(tmp_path))
    row = pd.read_csv(res["items_csv"]).iloc[0]
    assert row["discount_amount_cop"] == 1200
    assert row["discount_pct"] == 0.2


def test_vape_ignores_source_quantity_without_name_pack(tmp_path):
    pd = pytest.importorskip("pandas")
    from rappi_co.export import tobacco_deliverable as tex
    cls = [_cls("P", "s1", "Vapeador Glame GT 8000 Puffs", "vape_disposable")]
    menu = [{"product_id": "P", "store_id": "s1", "price_cop": 41800,
             "original_price_cop": 41800, "pack_count": 100, "quantity": 100,
             "pack_format_raw": "100Und", "store_name": "S"}]
    cpath, mpath = _write(tmp_path, cls, menu)
    res = tex.run_export(classifications_path=cpath, menu_path=mpath, out_dir=str(tmp_path))
    row = pd.read_csv(res["items_csv"]).iloc[0]
    assert pd.isna(row["pack_count"])
    assert pd.isna(row["unit_price_cop"])
