"""Regression tests for package contradictions and nutrition evidence boundaries."""
import json

import pytest

from rappi_co.enrich.beverage_fields import enrich_beverage


@pytest.mark.parametrize('name,volume', [
    ('2 Monster Bebida Energizante Energy', 473),
    ('3 Vino Tabernero Borgoña Semi Seco Botella 750 Ml', 750),
    ('24 Bebidas Energizantes Blow Up! Fresa 330 Ml', 330),
    ('2 Gatorade Bebida Isotonica Sabor Apple Ice', 500),
    ('2 Mikes Hard Bebida Preparada Con Jugo de Limon y Vodka', 355),
])
def test_archived_leading_counts_do_not_inherit_one_bottle(name, volume):
    out = enrich_beverage({'name': name, 'quantity': volume, 'unit_type': 'ml',
                           'pack_format_raw': f'1 X {volume} mL'})
    assert out['pack_count'] is None
    assert out['total_volume_ml'] is None
    assert 'ambiguous_title_count' in out['beverage_flags']


@pytest.mark.parametrize('name', [
    '7 Up Bebida Gaseosa Sabor Lima Limón', '3 Cordilleras Cerveza Mona',
    '5 Flores Vinto Tinto Malbec', '7 Vidas Cerveza Pale Ale',
    '7 Colores Vino Tinto Varietal Cabernet Sauvignon', '14 Inkas Vodka Artesanal',
    '4 Gallos Pisco',
])
def test_observed_numeric_brand_names_are_not_multipacks(name):
    out = enrich_beverage({'name': name, 'pack_format_raw': '1 X 500 mL'})
    assert out['pack_count'] == 1
    assert out['total_volume_ml'] == 500


@pytest.mark.parametrize('name', [
    'Heineken Cerveza Lata Medio X 6', 'Imperial Ipa X6 473 Ml',
    'Mr Tea Bebida Duopack', 'Aguila Cerveza Original Pack Lata',
    'Six Aguila Orig Lata. 355 Ml', 'Blow Up Energy Drink X 03 | 330 Ml - Strawberry Lush',
    'Coca-Cola Original Refresco Bipack 1.75L', 'Duo Cervezas Corona 330ml C/u',
    'Trio Pilsen Twelve De 355ml',
])
def test_archived_multipack_hints_override_single_presentation_denominator(name):
    out = enrich_beverage({'name': name, 'pack_format_raw': '1 X 473 mL'})
    assert out['pack_count'] is None
    assert out['total_volume_ml'] is None
    assert 'ambiguous_title_multipack' in out['beverage_flags']


def test_archived_promotion_is_not_single_beer_price_denominator():
    out = enrich_beverage({'name': '2 X 1 Cerveza Grolsch 500 Ml', 'pack_format_raw': '1Und'})
    assert out['total_volume_ml'] is None
    assert 'promotional_quantity_ambiguous' in out['beverage_flags']


def test_archived_concatenated_pack_unit_is_not_single_bottle():
    out = enrich_beverage({'name': 'Bonafont Kids Agua Con Jugo Natural de Naranja 6x300mLTapa Chupón',
                           'pack_format_raw': '1 X 300 mL'})
    assert out['total_volume_ml'] is None
    assert 'malformed_title_pack_unit' in out['beverage_flags']


@pytest.mark.parametrize('name,pack,count,total', [
    ('Michelob Ultra Nrb 330 X6', '6 x 330 mL', 6, 1980),
    ('Agua mineral X 500 ml', '1 x 500 ml', 1, 500),
    ('Gaseosa Coca Cola X 2.25l', '1 X 2.25 L', 1, 2250),
    ('Agua 6x330ml', '6 X 330 ml', 6, 1980),
    ('Agua 2x1.5 L', '2 X 1.5 L', 2, 3000),
])
def test_real_quantity_evidence_is_not_promotion(name, pack, count, total):
    out = enrich_beverage({'name': name, 'pack_format_raw': pack})
    assert out['pack_count'] == count
    assert out['total_volume_ml'] == total


def test_zero_abv_conflicting_with_explicit_platform_flag_is_blank():
    out = enrich_beverage({'name': 'Tecate Light Cerveza',
                           'attributes_json': {'abv': '0', 'is_zero_alcohol': False}})
    assert out['abv_pct'] is None
    assert 'zero_abv_conflicts_with_alcohol_flag' in out['beverage_flags']
    assert any(f['field'] == 'abv_pct' and f['value'] == 0 for f in json.loads(out['beverage_evidence_json']))


def test_explicit_zero_alcohol_variant_keeps_stated_zero_abv():
    out = enrich_beverage({'name': 'Cerveza sin alcohol',
                           'attributes_json': {'abv': '0', 'is_zero_alcohol': True}})
    assert out['abv_pct'] == 0


def test_nested_supplier_value_objects_keep_their_enclosing_units():
    out = enrich_beverage({'name': 'Gaseosa', 'attributes_json': {'supplier': {
        'volume_per_unit_ml': {'value': 500, 'unit': 'ml'},
        'sugar_g_per_100ml': {'value': 10, 'unit': 'g'},
        'pack_size': {'value': 'x1'},
    }}})
    assert out['volume_per_unit_ml'] == 500
    assert out['sugar_g_per_100ml'] == 10
    assert out['total_volume_ml'] == 500
    assert 'supplier.volume_per_unit_ml' in out['volume_per_unit_ml_source']


def test_named_attribute_value_objects_with_normalized_labels():
    out = enrich_beverage({'name': 'Cerveza', 'attributes_json': [
        {'name': 'abv_pct', 'value': 5, 'unit': '%'},
        {'name': 'volume_per_unit_ml', 'value': 330, 'unit': 'ml'},
    ]})
    assert out['abv_pct'] == 5
    assert out['volume_per_unit_ml'] == 330


@pytest.mark.parametrize('text', [
    'Menos de 1 g de azúcar por 100 ml', '< 1 g de azúcar por 100 ml',
    'Less than 1 g sugar per 100 ml',
])
def test_sugar_bounds_are_not_exact_values(text):
    out = enrich_beverage({'name': 'Gaseosa 500 ml', 'nutrition_text': text})
    assert out['sugar_g_per_100ml'] is None
    assert 'sugar_amount_is_bound' in out['beverage_flags']


def test_mass_denominator_cannot_inherit_earlier_volume_basis():
    out = enrich_beverage({'name': 'Gaseosa 500 ml', 'nutrition_text':
                           'Por 100 ml: calorías 10. Azúcar 3 g por 100 g.'})
    assert out['sugar_g_per_100ml'] is None
    assert 'sugar_amount_basis_unsupported' in out['beverage_flags']


def test_package_basis_does_not_contaminate_per_100ml_sugar():
    out = enrich_beverage({'name': 'Gaseosa 500 ml', 'nutrition_text':
                           'Por 100 ml: azúcares 4 g. Por envase: azúcares 20 g.'})
    assert out['sugar_g_per_100ml'] == 4
    assert 'sugar_amount_basis_unsupported' in out['beverage_flags']


def test_english_added_sugar_is_not_total_sugar():
    out = enrich_beverage({'name': 'Juice 500 ml', 'nutrition_text': 'Added sugars: 4 g per 100 ml'})
    assert out['sugar_g_per_100ml'] is None
    assert 'added_sugar_amount_not_total' in out['beverage_flags']


def test_explicit_container_serving_size_can_normalize_sugar():
    out = enrich_beverage({'name': 'Gaseosa botella 500 ml', 'nutrition_text':
                           'Tamaño de porción: 1 botella (250 ml). Por porción: azúcar 25 g.'})
    assert out['volume_per_unit_ml'] == 500
    assert out['serving_volume_ml'] == 250
    assert out['sugar_g_per_100ml'] == 10


def test_invalid_derived_sugar_concentration_is_not_exported():
    out = enrich_beverage({'name': 'Gaseosa 500 ml', 'nutrition_text':
                           'Porción: 10 ml. Por porción: azúcar 100 g.'})
    assert out['sugar_g_per_100ml'] is None
    assert 'invalid_sugar_g_per_100ml' in out['beverage_flags']


@pytest.mark.parametrize('name', ['Cerveza 5% alcohol p/p', 'Cerveza Alcohol: 5% w/w'])
def test_alcohol_mass_fraction_is_not_abv(name):
    out = enrich_beverage({'name': name})
    assert out['abv_pct'] is None
    assert 'alcohol_mass_fraction_not_abv' in out['beverage_flags']


def test_archived_supplier_abv_alias_keeps_original_evidence_path():
    out = enrich_beverage({'name': 'Absolut Vodka 40% Botella 750ml',
                           'attributes_json': {'pps_abv': 40, 'pps_volume': '750 ml'}})
    assert out['abv_pct'] == 40
    assert out['abv_pct_source'] == 'attributes_json.pps_abv'
    assert out['volume_per_unit_ml'] == 750


def test_archived_units_per_pack_contradicts_single_sale_presentation():
    out = enrich_beverage({'name': 'Cata Tinto Vino Tinto Vincorte',
                           'pack_format_raw': '1 X 1 L', 'attributes_json': {'units_per_pack': 3}})
    assert out['pack_count'] is None
    assert out['total_volume_ml'] is None
    assert 'conflicting_pack_count' in out['beverage_flags']
    assert 'attributes_json.units_per_pack' in out['pack_count_source']


def test_supplier_pack_placeholder_is_not_a_count():
    out = enrich_beverage({'name': 'Cerveza 355 ml',
                           'attributes_json': {'pps_pack_size': 'Purchasingunits'}})
    assert out['pack_count'] is None
    assert out['total_volume_ml'] is None


@pytest.mark.parametrize('name', [
    '6 x Speed Unlimited Energy Drink Zero Sugar 269 mL',
    '6 × Speed Unlimited Energy Drink Zero Sugar 269 mL',
    '6xSpeed Unlimited Energy Drink Zero Sugar 269 mL',
    '6 x Agua mineral 269 mL',
])
def test_explicit_leading_multiplier_preserves_count_without_assuming_volume_basis(name):
    out = enrich_beverage({'name': name})
    assert out['pack_count'] == 6
    assert 'ambiguous_title_count' not in out['beverage_flags']
    # Naming six drinks and a volume does not prove whether volume is per drink.
    assert out['volume_per_unit_ml'] is None
    assert out['total_volume_ml'] is None
    assert 'ambiguous_pack_volume_basis' in out['beverage_flags']


@pytest.mark.parametrize('multiplier', ['x', '×'])
def test_explicit_leading_quantity_and_volume_remain_a_valid_package(multiplier):
    out = enrich_beverage({'name': f'6 {multiplier} 269 mL Agua mineral'})
    assert out['pack_count'] == 6
    assert out['volume_per_unit_ml'] == 269
    assert out['total_volume_ml'] == 1614
    assert 'ambiguous_title_count' not in out['beverage_flags']


@pytest.mark.parametrize('row', [
    {'name': 'X6 Bebida Energética Body Fuel Applied Nutrition 330ml', 'pack_format_raw': '100Und'},
    {'name': 'Cerveza Sixpack 330ml', 'pack_format_raw': '1Und'},
    {'name': 'Cerveza Pack 330ml'},
    {'name': 'Mr Tea Bebida Duopack 500ml', 'pack_format_raw': '1Und'},
    {'name': '2 Bebidas energizantes 330ml', 'pack_format_raw': '1Und'},
])
def test_unresolved_pack_cardinality_cannot_promote_generic_volume_to_per_unit(row):
    out = enrich_beverage(row)
    assert out['pack_count'] is None
    assert out['volume_per_unit_ml'] is None
    assert out['total_volume_ml'] is None
    assert 'ambiguous_pack_volume_basis' in out['beverage_flags']


@pytest.mark.parametrize('operands', [
    {'volume_per_unit_ml': 330},
    {'attributes_json': {'volume_per_unit_ml': 330}},
    {'product_information': 'Cada botella: 330 ml'},
    {'product_information': 'Botellas de 330 ml'},
    {'pack_format_raw': '1 x 330 ml'},
])
def test_explicit_per_unit_operand_survives_unresolved_pack_count(operands):
    out = enrich_beverage({'name': 'Cerveza Pack 330ml', **operands})
    assert out['pack_count'] is None
    assert out['volume_per_unit_ml'] == 330
    assert out['total_volume_ml'] is None


def test_explicit_total_remains_a_denominator_when_only_cardinality_is_uncertain():
    out = enrich_beverage({'name': 'Cerveza Pack 330ml',
                           'attributes_json': {'total_volume_ml': 1980}})
    assert out['pack_count'] is None
    assert out['volume_per_unit_ml'] is None
    assert out['total_volume_ml'] == 1980
    assert out['total_volume_ml_source'] == 'attributes_json.total_volume_ml'


def test_matching_explicit_count_corroborates_bare_leading_quantity():
    out = enrich_beverage({'name': '24 Bebidas Energizantes Blow Up! Uva 330 Ml',
                           'pack_format_raw': '24Und'})
    assert out['pack_count'] == 24
    assert out['volume_per_unit_ml'] is None
    assert out['total_volume_ml'] is None
    assert 'ambiguous_title_count' not in out['beverage_flags']
