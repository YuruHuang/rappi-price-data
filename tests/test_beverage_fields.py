"""Adversarial, offline beverage facts: false precision is a failed extraction."""
import json

import pytest

from rappi_co.enrich.beverage_fields import enrich_beverage


@pytest.mark.parametrize("name,category", [
    ("Agua mineral con gas botella 600 ml", "water"),
    ("Agua natural 1.5 L", "water"),
    ("Agua sin gas 625 cc", "water"),
    ("Agua saborizada limón 600 ml", "review"),
    ("Agua tónica 350 ml", "review"),
    ("Gaseosa Cola 350 ml", "review"),
    ("Gaseosa Zero 350 ml", "non_ssb"),
    ("Refresco diet 355 ml", "non_ssb"),
    ("Néctar mango 1 L", "review"),
    ("Jugo 100% fruta sin azúcar añadida 1 L", "non_ssb"),
    ("Té frío sin endulzar 500 ml", "non_ssb"),
    ("Bebida energizante 250 ml", "review"),
    ("Bebida isotónica con azúcar 500 ml", "ssb"),
    ("Agua de panela 500 ml", "review"),
    ("Limonada endulzada con panela 500 ml", "ssb"),
    ("Cerveza lager 330 ml", "alcohol"),
    ("Vino tinto 750 ml", "alcohol"),
    ("Aguardiente sin azúcar 750 ml", "alcohol"),
    ("Whisky 12 años 750 ml", "alcohol"),
    ("Ron blanco 700 ml", "alcohol"),
    ("Pisco 750 ml", "alcohol"),
    ("Cerveza sin alcohol 330 ml", "review"),
    ("Cerveza sin alcohol sin azúcar 330 ml", "non_ssb"),
    ("Agua micelar 500 ml", "excluded"),
    ("Agua oxigenada 100 ml", "excluded"),
    ("Alcohol antiséptico 70% 500 ml", "excluded"),
    ("Gel antibacterial 70% alcohol 500 ml", "excluded"),
    ("Vasos para cerveza 6 unidades", "excluded"),
    ("Helado de ron 500 ml", "excluded"),
    ("Café molido 500 g", "excluded"),
    ("Refresco en polvo 20 g", "excluded"),
    ("Jarabe para bebidas 1 L", "excluded"),
])
def test_scope_and_sugar_status_are_conservative(name, category):
    assert enrich_beverage({"name": name})["beverage_category"] == category


@pytest.mark.parametrize("name,volume,count,total", [
    ("Agua 6 x 330 ml", 330, 6, 1980),
    ("Cerveza 330 ml x 6", 330, 6, 1980),
    ("Cerveza Six Pack 330 ml", None, 6, None),
    ("Agua 6 botellas 0,5 L", 500, 6, 3000),
    ("Agua botella 1,5 litros", 1500, 1, 1500),
    ("Cerveza lata 33 cl", 330, 1, 330),
    ("Agua 600 cc", 600, None, None),
    ("Agua 1.5 L", 1500, None, None),
])
def test_explicit_volume_and_counts(name, volume, count, total):
    out = enrich_beverage({"name": name})
    assert out["volume_per_unit_ml"] == volume
    assert out["pack_count"] == count
    assert out["total_volume_ml"] == total


def test_serving_and_nutrition_denominators_never_become_package_size():
    out = enrich_beverage({"name": "Gaseosa botella 500 ml", "product_information":
        "Tamaño de porción: 250 ml. Por porción: azúcares 25 g. Por 100 ml: sodio 20 mg."})
    assert out["volume_per_unit_ml"] == 500
    assert out["serving_volume_ml"] == 250
    assert out["sugar_g_per_serving"] == 25
    assert out["sugar_g_per_100ml"] == 10
    assert out["sugar_g_per_100ml_source"].startswith("derived:")


@pytest.mark.parametrize("information,sugar", [
    ("Azúcares: 10,6 g por 100 ml", 10.6),
    ("Por 100 ml: azúcares totales 11 g", 11),
    ("Sugar 25 g / 250 ml", 10),
    ("Azúcares: 0 g por 100 ml", 0),
    ("Carbohidratos: 10 g por 100 ml", None),
    ("Azúcares: 10 g", None),
    ("Sin azúcar", None),
    ("Zero", None),
    ("Azúcares añadidos: 10 g por 100 ml", None),
])
def test_sugar_has_a_named_nutrient_and_denominator(information, sugar):
    out = enrich_beverage({"name": "Gaseosa 500 ml", "product_information": information})
    assert out["sugar_g_per_100ml"] == sugar
    assert out["volume_per_unit_ml"] == 500


def test_added_sugar_is_not_total_but_proves_sweetening():
    out = enrich_beverage({"name": "Jugo 500 ml", "product_information":
        "Azúcares totales: 12 g por 100 ml. Azúcares añadidos: 4 g por 100 ml."})
    assert out["sugar_g_per_100ml"] == 12
    assert out["beverage_category"] == "ssb"


def test_natural_juice_sugar_alone_does_not_prove_added_sugar():
    out = enrich_beverage({"name": "Jugo de naranja 500 ml", "product_information":
        "Azúcares totales: 12 g por 100 ml."})
    assert out["beverage_category"] == "review"


def test_ingredient_sugar_proves_sweetening_but_sucralose_does_not():
    out = enrich_beverage({"name": "Gaseosa 500 ml", "product_information":
        "Ingredientes: agua carbonatada, azúcar, colorante."})
    assert out["beverage_category"] == "ssb"
    other = enrich_beverage({"name": "Gaseosa 500 ml", "product_information":
        "Ingredientes: agua carbonatada, sucralosa, colorante."})
    assert other["beverage_category"] == "review"


@pytest.mark.parametrize("text,abv", [
    ("Cerveza 5% vol", 5),
    ("Cerveza ABV: 4,5%", 4.5),
    ("Ron Alcohol: 40%", 40),
    ("Aguardiente 29 grados alcohólicos", 29),
    ("Vino 12% descuento", None),
    ("Jugo 100% fruta", None),
    ("Cerveza 5%", None),
    ("Cerveza 5 grados", None),
    ("Whisky 12 años", None),
])
def test_percent_and_age_are_not_alcohol_content(text, abv):
    assert enrich_beverage({"name": text})["abv_pct"] == abv


def test_structured_units_and_original_sources_survive():
    row = {"name": "Cerveza botella 330 ml", "attributes_json": json.dumps({
        "abv_pct": 4.5, "nutrition": {"sugar_g_per_100ml": 2.4},
    })}
    original = dict(row)
    out = enrich_beverage(row)
    assert row == original
    assert out["abv_pct"] == 4.5
    assert out["sugar_g_per_100ml"] == 2.4
    assert out["sugar_g_per_100ml_source"] == "attributes_json.nutrition.sugar_g_per_100ml"
    assert any(f["raw_text"] == "4.5" for f in json.loads(out["beverage_evidence_json"]))


def test_attribute_label_value_objects_are_not_lost():
    out = enrich_beverage({"name": "Cerveza 330 ml", "attributes_json": [
        {"name": "Alcohol", "value": "4.5", "unit": "%"},
        {"label": "Azúcares", "value": "2 g por 100 ml"},
    ]})
    assert out["abv_pct"] == 4.5
    assert out["sugar_g_per_100ml"] == 2


def test_title_detail_conflicts_blank_numeric_values_and_keep_both_facts():
    out = enrich_beverage({"name": "Cerveza botella 330 ml 4% vol", "product_information":
        "Contenido neto: 500 ml. Alcohol: 5%."})
    assert out["volume_per_unit_ml"] is None
    assert out["abv_pct"] is None
    assert "conflicting_volume_per_unit_ml" in out["beverage_flags"]
    assert "conflicting_abv_pct" in out["beverage_flags"]
    facts = json.loads(out["beverage_evidence_json"])
    assert {f["value"] for f in facts if f["field"] == "abv_pct"} == {4, 5}


def test_sugar_claim_conflict_is_review_not_silent_precedence():
    out = enrich_beverage({"name": "Gaseosa sin azúcar 500 ml", "product_information":
        "Ingredientes: agua, azúcar, colorante."})
    assert out["beverage_category"] == "review"
    assert out["sugar_status"] == "unknown"
    assert "conflicting_sugar_claims" in out["beverage_flags"]


@pytest.mark.parametrize("name", [
    "Combo ron 750ml + gaseosa 1.5 L", "Pack mixto cervezas 330 ml",
    "Agua 500ml + jugo 500ml", "Kit vino con copa 750 ml",
])
def test_bundles_have_no_homogeneous_unit_or_composition_inference(name):
    out = enrich_beverage({"name": name})
    assert out["beverage_category"] in {"review", "excluded"}
    assert out["volume_per_unit_ml"] is None
    assert out["total_volume_ml"] is None
    assert out["pack_count"] is None


def test_legacy_sugar_and_abv_regex_outputs_are_not_trusted():
    out = enrich_beverage({"name": "Cerveza 330 ml", "sugar_g_from_text": 15,
                           "abv_pct_from_text": 20, "abv_evidence": "20% descuento"})
    assert out["abv_pct"] is None
    assert out["sugar_g_per_100ml"] is None


@pytest.mark.parametrize("value", ["1.000", "1,000"])
def test_regional_punctuation_does_not_create_one_ml_water(value):
    out = enrich_beverage({"name": f"Agua mineral {value} ml", "volume_ml": 1, "pack_count": 1})
    assert out["volume_per_unit_ml"] is None
    assert out["total_volume_ml"] is None
    assert "ambiguous_volume_number_format" in out["beverage_flags"]


def test_real_platform_boolean_and_abv_attributes():
    no_sugar = enrich_beverage({"name": "Gaseosa 500ml", "attributes_json": {"sugar_free": True}})
    assert no_sugar["beverage_category"] == "non_ssb"
    assert no_sugar["sugar_g_per_100ml"] is None
    false = enrich_beverage({"name": "Gaseosa 500ml", "attributes_json": {"sugar_free": False}})
    assert false["beverage_category"] == "review"
    bad_abv = enrich_beverage({"name": "Cerveza 330ml", "attributes_json": {"abv": "50"}})
    assert bad_abv["beverage_category"] == "review"
    assert bad_abv["abv_pct"] is None
    assert "unusual_abv_requires_review" in bad_abv["beverage_flags"]
    assert any(f["value"] == 50 for f in json.loads(bad_abv["beverage_evidence_json"]))
    good_abv = enrich_beverage({"name": "Cerveza 330ml", "attributes_json": {"abv": "5"}})
    assert good_abv["abv_pct"] == 5


def test_real_platform_pack_size_format_and_explicit_container_volume():
    out = enrich_beverage({"name": "Cerveza lata 330ml", "attributes_json": {"pack_size": "x6"}})
    # Explicit platform pack beats a singular title's unsupported unit count.
    assert out["pack_count"] == 6
    assert out["total_volume_ml"] == 1980


def test_dedicated_detail_text_is_used_for_sweetening_and_nutrition():
    out = enrich_beverage({"name": "Gaseosa botella 500ml", "ingredients_text": "Agua, azúcar, colorante",
                           "nutrition_text": "Azúcar: 10 g por 100 ml"})
    assert out["beverage_category"] == "ssb"
    assert out["volume_per_unit_ml"] == 500
    assert out["sugar_g_per_100ml"] == 10
    assert "nutrition_text" in out["sugar_g_per_100ml_source"]


@pytest.mark.parametrize("name,category", [
    ("Agua de rosas 500ml", "excluded"),
    ("Botella de agua para mascotas 500ml", "excluded"),
    ("Café con azúcar 250 g", "excluded"),
    ("Agua saborizada con azúcar 500ml", "ssb"),
    ("Cerveza 0.0 330ml", "review"),
])
def test_external_review_scope_regressions(name, category):
    out = enrich_beverage({"name": name})
    assert out["beverage_category"] == category
    if category == "ssb":
        assert out["volume_per_unit_ml"] == 500


def test_reverse_sugar_amount_and_closest_denominator():
    out = enrich_beverage({"name": "Gaseosa 500ml", "nutrition_text":
        "Por 100 ml: 10 g de azúcares. Por porción: azúcar 25 g. Porción: 250 ml."})
    assert out["sugar_g_per_100ml"] == 10
    assert out["sugar_g_per_serving"] == 25
    assert out["serving_volume_ml"] == 250


def test_ambiguous_pack_volume_cannot_multiply_a_possible_total_again():
    out = enrich_beverage({"name": "Agua Pack 6 1980ml"})
    assert out["pack_count"] == 6
    assert out["volume_per_unit_ml"] is None
    assert out["total_volume_ml"] is None
    assert "ambiguous_pack_volume_basis" in out["beverage_flags"]


def test_unknown_legacy_volume_and_count_are_preserved_but_not_used():
    out = enrich_beverage({"name": "Agua", "volume_ml": 500, "pack_count": 1})
    assert out["volume_per_unit_ml"] is None
    assert out["pack_count"] is None
    facts = json.loads(out["beverage_evidence_json"])
    assert {fact["field"] for fact in facts} == {"unverified_legacy_volume_ml", "unverified_legacy_pack_count"}


def test_explicit_quantity_volume_unit_is_usable():
    out = enrich_beverage({"name": "Agua", "quantity": 1.5, "unit_type": "l"})
    assert out["volume_per_unit_ml"] == 1500
    assert out["volume_per_unit_ml_source"] == "listing.quantity/unit_type"


@pytest.mark.parametrize("name", [
    "Agua Sin Azúcar Saborizada H2OH! Sin Gas Limón 2000 cc",
    "Aquarius Agua Con Sabor a Naranja Sin Gas",
    "Agua Sin Gas Saborizada Pomelo Dia",
    "Maison Perrier Agua Con Gas Saborizada Durazno",
    "H2Oh! Agua Saborizadasin Gas Pomelo",
])
def test_live_argentina_flavored_water_is_not_plain_water(name):
    assert enrich_beverage({"name": name, "country_code": "ar"})["beverage_category"] != "water"


@pytest.mark.parametrize("name,category", [
    ("Soda en Botella Dia", "water"), ("Torasso Soda", "water"),
    ("Saldan Soda en Sifón", "water"), ("Cuisine & Co Soda Pura Agua", "water"),
    ("Hata Soda White Peach 300 Ml", "review"), ("Hata Soda Melon Cream 300 Ml", "review"),
    ("Booch Soda Probiótica De Burrito Y Jengibre", "review"),
    ("Sodastream Gasificadora de Agua Color Negra", "excluded"),
    ("Bebida Conc Sin Alcohol Sodastream Lima Limón", "excluded"),
    ("Terma Aperitivo Serrano sin Azúcar", "non_ssb"),
    ("Terma Aperitivo Sabor Limón", "review"),
    ("Fernet Branca 750ml", "alcohol"),
    ("McShake Chocolate", "review"), ("Leche sabor chocolate 1L", "review"),
    ("Tableta de Dulce de Leche con Chocolate", "excluded"),
])
def test_live_argentina_scope_rows(name, category):
    assert enrich_beverage({"name": name, "country_code": "ar"})["beverage_category"] == category


def test_local_soda_rule_does_not_turn_english_soda_into_water():
    assert enrich_beverage({"name": "Soda 355ml", "country_code": "us"})["beverage_category"] == "review"


@pytest.mark.parametrize("name", ["Quilmes Cerveza 6mL", "Cerveza Rubia361 1ml"])
def test_implausible_live_volume_cannot_create_per_litre_price(name):
    out = enrich_beverage({"name": name, "country_code": "ar"})
    assert out["beverage_category"] == "review"
    assert out["volume_per_unit_ml"] is None
    assert "unusual_volume_requires_review" in out["beverage_flags"]


def test_type_bearing_wine_attributes_with_stated_abv_establish_identity():
    out = enrich_beverage({"name": "Callia Malbec", "alcoholic_beverage": True,
        "attributes_json": {"abv": "13.5", "origin_wine": "Argentina", "varietal_wine": "Malbec"}})
    assert out["beverage_category"] == "alcohol"
    assert out["beverage_subcategory"] == "wine"
    assert out["abv_pct"] == 13.5


def test_cross_query_volume_conflict_blanks_the_affected_denominator():
    out = enrich_beverage({"name": "Agua mineral", "attributes_json": {"volume": "500ml", "pack_size": "x1"},
        "source_conflicts_json": [{"query": "agua mineral", "fields": {
            "attributes_json": {"first": {"volume": "500ml", "pack_size": "x1"},
                                "later": {"volume": "600ml", "pack_size": "x1"}}}}]})
    assert out["beverage_category"] == "review"
    assert out["volume_per_unit_ml"] is None
    assert out["total_volume_ml"] is None
    assert out["pack_count"] == 1
    assert "cross_query_composition_conflict" in out["beverage_flags"]
    assert any(f["source"].startswith("duplicate_query") for f in json.loads(out["beverage_evidence_json"]))


def test_cross_query_price_change_keeps_composition():
    out = enrich_beverage({"name": "Agua botella 500ml", "source_conflicts_json": [
        {"query": "agua mineral", "fields": {"price_local": {"first": 100, "later": 110}}}]})
    assert out["beverage_category"] == "water"
    assert out["volume_per_unit_ml"] == 500
    assert out["total_volume_ml"] == 500
    assert "source_conflict" in out["beverage_flags"]
    assert "cross_query_composition_conflict" not in out["beverage_flags"]


def test_cross_query_immaterial_attribute_change_keeps_composition():
    out = enrich_beverage({"name": "Agua botella 500ml", "attributes_json": {"packaging": "Botella"},
        "source_conflicts_json": [{"query": "agua mineral", "fields": {
            "attributes_json": {"first": {"packaging": "Botella"}, "later": {"packaging": "PET"}}}}]})
    assert out["beverage_category"] == "water"
    assert out["volume_per_unit_ml"] == 500
    assert "cross_query_composition_conflict" not in out["beverage_flags"]


def test_later_outlier_conflict_also_invalidates_first_stated_abv():
    out = enrich_beverage({"name": "Cerveza 330ml", "attributes_json": {"abv": "5"},
        "source_conflicts_json": [{"query": "cerveza lager", "fields": {
            "attributes_json": {"first": {"abv": "5"}, "later": {"abv": "50"}}}}]})
    assert out["abv_pct"] is None
    assert out["beverage_category"] == "review"
    assert "cross_query_conflicting_abv_pct" in out["beverage_flags"]


@pytest.mark.parametrize("name", ["Coto Coctel De Frutas Dietetico", "Carrefour Coctel De Frutas", "Cuisine & Co Coctel De Frutas"])
def test_live_mass_denominated_fruit_cocktail_is_food(name):
    out = enrich_beverage({"name": name, "quantity": 800, "unit_type": "gr",
                          "attributes_json": {"fruit_type": "Multiple", "volume": "800 g"},
                          "alcoholic_beverage": False})
    assert out["beverage_category"] == "excluded"
    assert out["beverage_subcategory"] == "fruit_preparation"


def test_fruit_cocktail_with_no_amount_does_not_establish_alcohol():
    out = enrich_beverage({"name": "Coctel de frutas"})
    assert out["beverage_category"] == "review"
    assert out["abv_pct"] is None


def test_leading_multiplier_conflicts_with_single_unit_presentation():
    out = enrich_beverage({"name": "6 x Brahma Cerveza", "quantity": 473, "unit_type": "ml",
                          "pack_format_raw": "1 X 473 mL"})
    assert out["volume_per_unit_ml"] == 473
    assert out["pack_count"] is None
    assert out["total_volume_ml"] is None
    assert "conflicting_pack_count" in out["beverage_flags"]


def test_iced_tea_name_is_not_ice_cream_but_mass_only_tea_is_dry():
    ready = enrich_beverage({"name": "Té helado limón 500ml"})
    assert ready["beverage_category"] == "review"
    assert ready["beverage_subcategory"] == "tea_coffee"
    dry = enrich_beverage({"name": "Saint Gottard té Helado Limón Jengibre y Menta",
                          "quantity": 25, "unit_type": "gr", "pack_format_raw": "1 x 25 g"})
    assert dry["beverage_category"] == "excluded"
    assert dry["beverage_subcategory"] == "dry_tea_coffee"


def test_beverage_and_ice_bundle_is_retained_for_component_review():
    out = enrich_beverage({"name": "Fernet branca 750 + coca 2,25 lt + hielo"})
    assert out["beverage_category"] == "review"
    assert out["volume_per_unit_ml"] is None
    assert out["total_volume_ml"] is None


def test_beer_zero_is_not_a_sugar_free_statement():
    out = enrich_beverage({"name": "Cerveza Zero 330ml", "attributes_json": {"is_zero_alcohol": True}})
    assert out["beverage_category"] == "review"
    assert out["sugar_status"] == "unknown"
    explicit = enrich_beverage({"name": "Cerveza Zero Sin Azúcar 330ml", "attributes_json": {"is_zero_alcohol": True}})
    assert explicit["beverage_category"] == "non_ssb"
    assert explicit["sugar_status"] == "no_sugar_claim"


@pytest.mark.parametrize("name,unit_type", [
    ("Carne al vino", "gr"), ("Pollo a la cerveza 500g", "gr"),
    ("Lomo al whisky", ""), ("Coctel de camarones", "gr"),
])
def test_prepared_food_with_alcohol_ingredient_is_not_alcohol_beverage(name, unit_type):
    assert enrich_beverage({"name": name, "unit_type": unit_type})["beverage_category"] == "excluded"


@pytest.mark.parametrize("name,category", [
    ("Felfort Licor", "review"), ("Alco Cóctel", "review"),
    ("Agua Viva Frutas Deshidratadas Limon, Naranja Y Pomelo", "excluded"),
])
def test_other_mass_only_food_collisions_cannot_enter_core_beverages(name, category):
    out = enrich_beverage({"name": name, "unit_type": "gr", "quantity": 200})
    assert out["beverage_category"] == category


def test_explicit_liquid_volume_survives_a_mass_unit_metadata_error():
    out = enrich_beverage({"name": "Cerveza botella 330ml", "unit_type": "gr", "quantity": 330})
    assert out["beverage_category"] == "alcohol"
    assert out["volume_per_unit_ml"] == 330


def test_live_cocktail_base_is_not_a_ready_to_drink_alcohol_product():
    out = enrich_beverage({"name": "Finest Call Base de Cóctel Triple Sec",
                          "alcoholic_beverage": True,
                          "attributes_json": {"cocktail_bases": "Mix", "volume": "1L"}})
    assert out["beverage_category"] == "excluded"
    assert out["volume_per_unit_ml"] == 1000


@pytest.mark.parametrize("name", [
    "Agua Funcional Cristalite Limonada de Coco600mL",
    "Agua Gasificada Con Inulina Aloe Vera X310ml Fit Cook",
    "Agua Gasificada Con Inulina Blueberry FlorDeJamaica X310ml Fit Cook",
])
def test_live_functional_water_is_not_plain_drinking_water(name):
    out = enrich_beverage({"name": name})
    assert out["beverage_category"] == "review"
    assert out["beverage_subcategory"] == "flavored_water"
    assert out["volume_per_unit_ml"] in {310, 600}


def test_live_ginger_beer_mixer_requires_positive_alcohol_evidence():
    row = {"name": "Mil976 Mezclador Ginger Beer y Limón Botella",
           "alcoholic_beverage": True,
           "attributes_json": {"soda_type": "Sabores", "sugar_free": True, "volume": "250ml"}}
    out = enrich_beverage(row)
    assert out["beverage_category"] == "review"
    assert out["sugar_status"] == "no_sugar_claim"
    explicit = enrich_beverage({**row, "product_information": "Alcohol 5% vol"})
    assert explicit["beverage_category"] == "alcohol"


@pytest.mark.parametrize("name", [
    "Protein Water Lemon", "Protein Water Limón", "Vitamin Water 500ml",
    "Collagen Water 500ml", "Electrolyte Water 500ml", "Infused Water 500ml",
    "Erza Agua de Azahar",
])
def test_live_peru_functional_and_botanical_waters_need_review(name):
    out = enrich_beverage({"name": name, "country_code": "pe"})
    assert out["beverage_category"] == "review"
    assert out["beverage_subcategory"] == "flavored_water"


@pytest.mark.parametrize("name,volume", [
    ("2 Agua Sin Gas Cielo", 1000), ("2 San Mateo Agua Mineral Con Gas", 600),
])
def test_live_peru_leading_water_integer_invalidates_single_bottle_denominator(name, volume):
    out = enrich_beverage({"name": name, "country_code": "pe", "unit_type": "ml",
                          "quantity": volume, "pack_format_raw": f"1 x {volume} ml"})
    assert out["volume_per_unit_ml"] == volume
    assert out["pack_count"] is None
    assert out["total_volume_ml"] is None
    assert "ambiguous_title_count" in out["beverage_flags"]


@pytest.mark.parametrize("name", [
    "Agua de Limón", "Agua Fresca de Jamaica", "Agua Chica de Jamaica",
    "Agua de Litro de Piña", "AGUA LIMÓN CHÍA MED", "500 ml Agua de Limon",
    "Peñafiel Agua Mineral Soft Seltzer Limón", "Aje Vida Agua Gasificada Búho Limón",
    "Bonafont Aguas Frescas Guayaba 1 L", "AGUA TORONJA GDE", "AGUA AVENA MED",
    "AGUA MAMEY GDE", "AGUA TAMARINDO MED", "AGUA MARACUYÁ GDE", "AGUA MELÓN MED",
    "AGUA PAPAYA MED", "AGUA SANDÍA GDE", "AGUA GUANÁBANA MED", "AGUA HIERBABUENA",
    "AGUA HORCHATA GDE",
])
def test_live_mexico_fruit_and_herb_water_titles_are_flavored_candidates(name):
    out = enrich_beverage({"name": name, "country_code": "mx"})
    assert out["beverage_category"] == "review"
    assert out["beverage_subcategory"] == "flavored_water"


def test_live_mexico_flavored_water_with_explicit_no_sugar_is_comparison():
    out = enrich_beverage({"name": "Agua Bonafont Manzana Sin Azúcar", "country_code": "mx"})
    assert out["beverage_category"] == "non_ssb"
    assert out["sugar_g_per_100ml"] is None


@pytest.mark.parametrize("name", ["Paleta Fresa Agua", "Lime Water Ice Pop", "Envase Para Agua Glacier Water 20L"])
def test_live_mexico_frozen_food_and_water_container_collisions(name):
    assert enrich_beverage({"name": name, "country_code": "mx"})["beverage_category"] == "excluded"


def test_leading_number_with_explicit_pack_noun_is_not_an_ambiguous_title_count():
    out = enrich_beverage({"name": "12 Pack de Agua Natural Bonafont 600 ml"})
    assert out["pack_count"] == 12
    assert "ambiguous_title_count" not in out["beverage_flags"]
