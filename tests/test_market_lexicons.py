import pytest

from rappi_co.classify.stage_c_overrides import apply_overrides
from rappi_co.classify.tobacco_classifier import classify_item, load_market_lexicon


@pytest.mark.parametrize("country,name,section,expected_type", [
    ("ar", "Dolchester Blue", None, "cigarette"),
    ("ar", "Red Point Box 20", "Cigarrillos", "cigarette"),
    ("pe", "VIKA Fresh Mint", "Pouches", "nicotine_pouch"),
    ("mx", "VHILL 10000 Puffs", None, "vape"),
    ("co", "MTRX 25000 Puffs", None, "vape"),
])
def test_country_brand_extensions(country, name, section, expected_type):
    result = classify_item({"name": name, "menu_section": section},
                           load_market_lexicon(country))
    assert result.primary_class == "tobacco"
    assert result.product_type == expected_type


def test_context_brand_still_needs_tobacco_evidence():
    result = classify_item({"name": "Master Chef Premium"}, load_market_lexicon("ar"))
    assert result.primary_class == "out_of_scope"
    assert "oos_context_unconfirmed:master" in result.flags


def test_compact_brand_spelling_is_added_to_market_lexicon():
    result = classify_item({"name": "Elfbar Strawberry Spark 40k"},
                           load_market_lexicon("ar"))
    assert result.primary_class == "tobacco"
    assert result.product_type == "vape_disposable"


@pytest.mark.parametrize("country,name,expected_type", [
    ("ar", "Vapers Baja Splash", "vape"),
    ("ar", "Chesterfiel De 20 Bluemotion Comun", "cigarette"),
    ("co", "Glu Cloud Strawberry Ice XL", "vape"),
    ("pe", "Pall Click On 10", "cigarette"),
    ("ar", "Extre-bar Strawberry B. Burst", "vape"),
    ("co", "Lucky Alaska", "cigarette"),
    ("co", "LyM Blue Cigarrillos", "cigarette"),
    ("co", "Cigarrillo Malboro Rosa", "cigarette"),
])
def test_observed_market_spellings(country, name, expected_type):
    section = "Vaporizadores y dispositivos" if expected_type == "vape" else "Cigarrillos"
    result = classify_item({"name": name, "menu_section": section},
                           load_market_lexicon(country))
    assert result.primary_class == "tobacco"
    assert result.product_type == expected_type


def test_bare_household_vaporizador_is_not_a_study_tobacco_signal():
    result = classify_item(
        {"name": "Iberia Vaporizador", "menu_section": "Vaporizadores y dispositivos"},
        load_market_lexicon("ar"),
    )
    assert result.primary_class == "out_of_scope"


def test_vaper_spelling_survives_a_mis_shelved_accessory_aisle():
    for name in ("Vaper Orion Bar 10 K Pineapple Lemonade",
                 "Extre-bar Strawberry B. Burst"):
        item = {"name": name, "menu_section": "Otros accesorios de cigarrillos"}
        stage_a = classify_item(item, load_market_lexicon("ar")).as_dict()
        result = apply_overrides({**item, **stage_a}, study_mode=True)
        assert result["primary_class"] == "tobacco", name
        assert result["product_type"] == "vape", name


def test_vaper_accessory_is_still_paraphernalia():
    result = classify_item(
        {"name": "Encendedor Vaper", "menu_section": "Cigarrillos"},
        load_market_lexicon("ar"),
    )
    assert result.primary_class == "out_of_scope"
    assert "tobacco_paraphernalia" in result.flags


@pytest.mark.parametrize("country,name,expected_type", [
    ("mx", "Pall Mall Cigarro Tokyo XL", "cigarette"),
    ("pe", "Cigarro Cohiba Robusto", "cigar"),
    ("pe", "Nasty Juice Passion Killa 6mg", "vape_liquid"),
    ("ar", "Excellent Menthol Pouch 30 Gr", "rolling_tobacco"),
    ("co", "Pouches Cuba White Cola 10 Mg", "nicotine_pouch"),
    ("co", "TEREA Amber Cajetilla X 20", "heated_tobacco"),
    ("pe", "Bagz Nic Pouches Mint 8mg X15.6gr", "nicotine_pouch"),
    ("ar", "Pueblo Tabaco Natural Clasico", "rolling_tobacco"),
    ("pe", "Tabaco Para Armar Cigarrillos Golden", "rolling_tobacco"),
    ("mx", "Flor Morada Tabaco Natural", "rolling_tobacco"),
    ("ar", "Tabaco Luckies Golden", "rolling_tobacco"),
    ("co", "Macondo Cigarro Tabaco Macondo", "cigar"),
    ("pe", "Cigarro Device Gold", "vape"),
    ("ar", "Cafe Creme Cigarrillo Arome", "cigar"),
    ("ar", "Cigarrillo Handelsgold Blue", "cigar"),
    ("ar", "Cigarillos Exo Classic", "cigar"),
    ("mx", "Camel Tabaco Filters Original 25S", "cigarette"),
])
def test_market_product_type_disambiguation(country, name, expected_type):
    result = classify_item({"name": name, "menu_section": "Cigarrillos"},
                           load_market_lexicon(country))
    assert result.primary_class == "tobacco"
    assert result.product_type == expected_type


def test_cross_category_brand_is_flagged_for_local_review():
    result = classify_item({"name": "Glucloud Mint"}, load_market_lexicon("co"))
    assert result.primary_class == "tobacco"
    assert result.product_type is None
    assert "study_type_unresolved" in result.flags
