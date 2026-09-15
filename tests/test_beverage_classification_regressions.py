"""Second-pass regressions from eight-zone accepted/excluded/unknown strata.

IDs below refer to preserved original observations, not inferred brand recipes.
"""
import pytest

from rappi_co.enrich.beverage_fields import enrich_beverage


@pytest.mark.parametrize("name,attributes,family,category", [
    ("Monster Mango Loco 473 Ml", {"flavor_energy_drinks": "Mango"}, "energy_drink", "review"),
    ("Powerade Frutas Tropicales 500 Ml", {"isotonic_flavor": "Frutas Tropicales"}, "sports_drink", "review"),
    ("Inca Kola Sabor Original 600Ml", {"soda_type": "Sabores"}, "soft_drink", "review"),
    ("Sprite", {"soda_type": "Sabores", "sugar_free": True}, "soft_drink", "non_ssb"),
    ("Aquarius Manzana 1,5 Lt", {"flavored_water_flavor": "Manzana"}, "flavored_water", "review"),
    ("Be Light Jamaica 1 Lts Pet", {"flavored_water_flavor": "Jamaica", "sugar_free": True}, "flavored_water", "non_ssb"),
    ("Cepita Del Valle Naranja 1 Lt", {"flavor_juices": "Naranja"}, "juice", "review"),
    ("Lipton Durazno 600 Ml Pet", {"ready_tea_flavor": "Durazno"}, "tea_coffee", "review"),
    ("Alpina Avena Original Pack 6x200ml", {"cereal_drinks_flavor": "Natural"}, "other_beverage", "review"),
    ("Stella Artois Botella 330 Ml", {"beer_style": "Lager"}, "beer", "alcohol"),
    ("Etiqueta Reserva 750 ml", {"varietal_wine": "Malbec"}, "wine", "alcohol"),
    ("Pigskin London Dry", {"gin_style": "London Dry", "abv": 45}, "spirits", "alcohol"),
    ("Sin nombre 500 ml", {"pps_isotonic_flavor": "Mora"}, "sports_drink", "review"),
    ("Alpin Multisabor Caja 200 mL x 6 Und", {"flavored_milk_flavor": "Vainilla"}, "dairy_beverage", "review"),
    ("La Botija 750 ml", {"pisco_type": "Puro"}, "spirits", "alcohol"),
])
def test_explicit_attribute_types_recover_family_without_inventing_sugar(name, attributes, family, category):
    result = enrich_beverage({"name": name, "attributes_json": attributes})
    assert result["beverage_subcategory"] == family
    assert result["beverage_category"] == category
    assert result["sugar_g_per_100ml"] is None
    assert result["sugar_status"] != "sugar_sweetened"


@pytest.mark.parametrize("attributes", [
    {"brand": "Monster", "flavor": "Mango", "volume": "473 mL"},
    {"packaging": "Botella", "sugar_free": True},
    {"soda_type": ""},
    {"ready_tea_flavor": False},
])
def test_generic_attributes_do_not_establish_beverage(attributes):
    result = enrich_beverage({"name": "Producto", "attributes_json": attributes,
                              "source_terms": "bebida energética"})
    assert (result["beverage_category"], result["beverage_subcategory"]) == ("review", "unknown")


@pytest.mark.parametrize("name,attributes,category,family", [
    # AR 127153/562121 and 248235/539123 were incorrectly excluded by 'chocolate'.
    ("Cusenier Licor de Chocolate", {"abv": 17, "volume": "700 mL"}, "alcohol", "spirits"),
    ("Tres Plumas Licor de Chocolate con Dulce de Leche", {"volume": "700 mL"}, "alcohol", "spirits"),
    # MX 1923685541/755142; CO 6664043/379391 and 6664043/807946.
    ("Malteada de chocolate", {}, "review", "dairy_beverage"),
    ("Alpina Avena Original Vaso 250 g", {"cereal_drinks_flavor": "Natural"}, "review", "other_beverage"),
    ("Finesse Avena Vaso", {"cereal_drinks_flavor": "Natural", "sugar_free": True}, "non_ssb", "other_beverage"),
    # PE 2530/1074103436 is a beverage containing concentrated juice.
    ("San Pellegrino Bebida Carbonatada con Jugo de Limón Concentrado", {"volume": "330 mL"}, "review", "juice"),
    # PE 27182/2092817676; the cocktail label does not establish alcohol.
    ("Welchs Jugo Cocktail Cranberry", {"flavor_juices": "Arándano", "volume": "295 mL"}, "review", "juice"),
])
def test_contextual_false_positives_and_false_exclusions(name, attributes, category, family):
    result = enrich_beverage({"name": name, "attributes_json": attributes})
    assert (result["beverage_category"], result["beverage_subcategory"]) == (category, family)


@pytest.mark.parametrize("name,attributes", [
    ("Clight Refresco Mandarina sin Calorias", {"powdered_beverages_flavor": "Mandarina", "sugar_free": True, "volume": "2 L"}),
    ("Margarita", {"cocktail_bases": "Juice", "volume": "1 L"}),
    ("Bebida en Polvo", {"isotonic_flavor": "Limón", "volume": "1 L"}),
    ("Gel Energético Fuelr Isotónico 60 Ml", {}),
    ("Chocolate con Licor", {}),
    ("Bombón de chocolate con ron", {}),
    ("Vaso para bebida 500 ml", {"flavor_juices": "Mango"}),
    ("Roy Copa L'Esprit du Vin Champagne", {"varietal_wine": "Chardonnay", "abv": 12}),
    ("Agua Desmineralizada", {"volume": "5 L"}),
])
def test_nonready_and_nonbeverage_evidence_still_excludes(name, attributes):
    assert enrich_beverage({"name": name, "attributes_json": attributes})["beverage_category"] == "excluded"


@pytest.mark.parametrize("claim", [
    "sin azúcar añadida", "sin azúcares añadidos", "sin azúcar agregada",
    "sin azúcares adicionados", "no added sugar",
])
def test_no_added_sugar_is_not_total_sugar_free(claim):
    result = enrich_beverage({"name": f"Jugo {claim} 1 L", "nutrition_text": "Azúcares totales 9 g por 100 ml"})
    assert result["sugar_status"] == "no_added_sugar_claim"
    assert result["sugar_g_per_100ml"] == 9
    assert result["beverage_category"] == "non_ssb"
    assert "conflicting_sugar_claims" not in result["beverage_flags"]


def test_added_sugar_claim_and_caloric_sweetener_conflict():
    result = enrich_beverage({"name": "Jugo sin azúcares añadidos", "ingredients_text": "Agua, azúcar, jugo de naranja"})
    assert result["beverage_category"] == "review"
    assert "conflicting_sugar_claims" in result["beverage_flags"]


@pytest.mark.parametrize("name,attributes,expected", [
    ("Hatsu Agua Con Gas", {"flavor": "Gulupa", "sugar_free": True}, "non_ssb"),
    ("Agua Sin Gas", {"flavor": "Natural"}, "water"),
    ("Agua Natural", {"flavor_drinks": "Mora"}, "review"),
])
def test_water_flavor_attributes_preserve_plain_water_boundary(name, attributes, expected):
    assert enrich_beverage({"name": name, "attributes_json": attributes})["beverage_category"] == expected


@pytest.mark.parametrize("name", ["Néctar Aguardiente Club sin Azúcar", "Ron Añejo", "Cerveza Lager"])
def test_zero_abv_alone_does_not_establish_nonalcoholic_variant(name):
    result = enrich_beverage({"name": name, "attributes_json": {"abv": 0}})
    assert result["beverage_category"] == "review"
    assert "zero_abv_without_nonalcoholic_identity" in result["beverage_flags"]


def test_misspelled_explicit_nonalcoholic_title_stays_unresolved():
    result = enrich_beverage({"name": "Welchs Espumante Rosé Sin Alcochol Non Alcoh"})
    assert result["beverage_category"] == "review"
    assert "nonalcoholic_variant" in result["beverage_flags"]


def test_conflicting_attribute_identity_cannot_confirm_alcohol():
    result = enrich_beverage({"name": "Producto 500 ml", "attributes_json": {"beer_style": "Lager", "soda_type": "Cola"}})
    assert result["beverage_category"] == "review"
    assert "conflicting_typed_beverage_identity" in result["beverage_flags"]


@pytest.mark.parametrize("name,attributes", [
    ("Gaseosa 500 ml", {"beer_style": "Lager", "sugar_free": True}),
    ("Agua 500 ml", {"soda_type": "Sabores"}),
    ("Cerveza 500 ml", {"flavor_juices": "Mango"}),
])
def test_title_and_typed_identity_conflict_remains_review(name, attributes):
    result = enrich_beverage({"name": name, "attributes_json": attributes})
    assert result["beverage_category"] == "review"
    assert "conflicting_typed_beverage_identity" in result["beverage_flags"]


@pytest.mark.parametrize("name", [
    "Malteada Chocolate en Polvo", "Leche Chocolate en Polvo",
    "Té Helado en Polvo", "Té Helado Jarabe Concentrado",
    "Bebida Vaso en Polvo", "Bebida Vaso Chocolate Helado",
    "Licor de Chocolate Helado", "Caja de Chocolates con Ron",
    "Chocolate con leche 100 g", "Bebida con Jugo Concentrado en Polvo",
])
def test_contextual_exception_cannot_hide_later_exclusion(name):
    assert enrich_beverage({"name": name})["beverage_category"] == "excluded"


def test_contradictory_confectionery_attributes_do_not_confirm_liqueur():
    result = enrich_beverage({"name": "Tres Plumas Licor Fino de Chocolate Amargo",
                              "attributes_json": {"chocolate_type": "Amargo", "chocolate_filling": "Sin relleno"}})
    assert result["beverage_category"] == "review"
    assert "conflicting_beverage_food_identity" in result["beverage_flags"]


def test_tabletop_sweetener_is_not_a_mate_drink():
    result = enrich_beverage({"name": "Hileret Endulzante Mate Líquido Clásico",
                              "attributes_json": {"sweetener_type": "Aspartamo", "volume": "200 mL"}})
    assert (result["beverage_category"], result["beverage_subcategory"]) == ("excluded", "table_sweetener")


def test_beverage_with_sweetener_attribute_is_not_a_tabletop_product():
    result = enrich_beverage({"name": "Bebida con endulzante 500 ml", "attributes_json": {"sweetener_type": "Sucralosa"}})
    assert result["beverage_category"] == "review"
    assert result["sugar_status"] == "unknown"
