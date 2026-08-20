"""FP/FN battery for the Colombia tobacco classifier.

Run:  python -m pytest tests/test_tobacco_classifier.py -q  (from the repo root)

The goal is to lock the two error directions:
  * FALSE NEGATIVES — every genuine tobacco/nicotine item must classify `tobacco`.
  * FALSE POSITIVES — collision brands, candy "cigarettes", and paraphernalia
    must NOT classify `tobacco` (paraphernalia/candy are captured-but-tagged).
Examples use Colombian brands (Pielroja, Boston, Mustang, Caribe, Premier, ...).
"""
import pytest

from rappi_co.classify.tobacco_classifier import classify_item, load_lexicon

LEX = load_lexicon()


def C(name, brand=None, section=None, subsection=None, antismoking=False):
    return {
        "name": name, "brand": brand, "menu_section": section,
        "menu_subsection": subsection, "has_antismoking": antismoking,
    }


# --------------------------------------------------------------------------- #
# TRUE POSITIVES — must be tobacco (no false negatives), with product_type
# --------------------------------------------------------------------------- #
POSITIVES = [
    (C("Marlboro Box x20", brand="Marlboro", section="Cigarrillos"), "cigarette"),
    (C("Cigarrillos Pielroja Sin Filtro x14", brand="Pielroja", section="Cigarrillos"), "cigarette"),
    (C("Chesterfield Original x20"), "cigarette"),
    (C("Lucky Strike Click x20"), "cigarette"),
    (C("Cigarrillos L&M Azul x20", brand="L&M"), "cigarette"),
    (C("Tabaco para armar x30g"), "rolling_tobacco"),
    (C("Cigarro Cohiba Robusto", section="Cigarros"), "cigar"),
    (C("ZYN Cool Mint bolsita de nicotina"), "nicotine_pouch"),
    (C("VELO Bolsitas de Nicotina Ice 10mg"), "nicotine_pouch"),
    (C("IQOS HEETS Amber Selection"), "heated_tobacco"),
    (C("Juul Pod Virginia Tobacco"), "vape_pod"),
    (C("Elf Bar 600 puffs Watermelon"), "vape_disposable"),
    (C("Vape descartable Waka 6000"), "vape_disposable"),
    (C("Nicotina liquida nic salt 20mg"), "vape_liquid"),
]


@pytest.mark.parametrize("item,expected_type", POSITIVES)
def test_true_positives(item, expected_type):
    r = classify_item(item, LEX)
    assert r.primary_class == "tobacco", f"FALSE NEGATIVE: {item['name']} -> {r.rationale}"
    assert r.product_type == expected_type, (
        f"{item['name']}: product_type {r.product_type} != {expected_type}")


# --------------------------------------------------------------------------- #
# SCOPE: NRT + zero-nicotine vapes are IN-SCOPE with flags
# --------------------------------------------------------------------------- #
def test_nrt_in_scope_flagged():
    r = classify_item(C("Nicorette Chicle 2mg", brand="Nicorette", section="Salud"), LEX)
    assert r.primary_class == "tobacco"
    assert r.product_type == "nrt"
    assert "nrt" in r.flags


def test_zero_nicotine_vape_in_scope_flagged():
    r = classify_item(C("Vape descartable sin nicotina 0 mg"), LEX)
    assert r.primary_class == "tobacco"
    assert "zero_nicotine" in r.flags


@pytest.mark.parametrize("name", [
    "Vape Lost Mary Lemon Mint Zero Nicotine 5k",
    "Vape Raz 25.000 Puffs 0% Nic. Razzle Dazzle",
])
def test_zero_nicotine_catalog_variants_are_flagged(name):
    r = classify_item(C(name), LEX)
    assert r.primary_class == "tobacco"
    assert "zero_nicotine" in r.flags


# --------------------------------------------------------------------------- #
# CONTEXT-REQUIRED brands (Boston/Caribe/Mustang/...): confirmed -> tobacco
# --------------------------------------------------------------------------- #
CONFIRMED = [
    C("Boston Rojo x20", brand="Boston", section="Cigarrillos"),            # section
    C("Caribe Suave x20", brand="Caribe", section="Cigarrillos y Tabaco"), # section
    C("Mustang", brand="Mustang", section="Almacen", antismoking=True),     # antismoking
    C("Boston cajetilla x20", brand="Boston", section="Almacen"),           # corroborator 'cajetilla'
]


@pytest.mark.parametrize("item", CONFIRMED)
def test_context_required_confirmed(item):
    r = classify_item(item, LEX)
    assert r.primary_class == "tobacco", f"should confirm: {item} -> {r.rationale}"
    assert any(f.startswith("context_confirmed") for f in r.flags)


# --------------------------------------------------------------------------- #
# FALSE-POSITIVE traps — must NOT be tobacco
# --------------------------------------------------------------------------- #
# Collision brands with no tobacco context -> out_of_scope + recall-log flag.
COLLISIONS = [
    (C("Galletas Boston Chips", section="Mercado"), "boston"),
    (C("Mochila Camel Active", brand="Camel", section="Bazar"), "camel"),
    (C("Gaseosa Premier Naranja", brand="Premier", section="Bebidas"), "premier"),
    (C("Box organizador plastico", section="Hogar"), "box"),
    (C("Bebida Caribe Cola 1.5L", brand="Caribe", section="Bebidas"), "caribe"),
    (C("Mango Kent x kg", section="Frutas y Verduras"), "kent"),
    (C("Cerveza Imperial Lata 330ml", brand="Imperial", section="Cervezas"), "imperial"),
    (C("Panuelos Next x100", brand="Next", section="Aseo"), "next"),
]


@pytest.mark.parametrize("item,brand_tok", COLLISIONS)
def test_collision_not_tobacco(item, brand_tok):
    r = classify_item(item, LEX)
    assert r.primary_class == "out_of_scope", (
        f"FALSE POSITIVE: {item['name']} wrongly tobacco ({r.rationale})")
    assert any(f"oos_context_unconfirmed:{brand_tok}" in f for f in r.flags), (
        f"{item['name']}: expected recall-log flag, got {r.flags}")


# Candy / chocolate cigarettes -> out_of_scope, captured with candy flag.
def test_candy_cigarette_demoted():
    r = classify_item(C("Cigarrillos de chocolate Jet", section="Golosinas"), LEX)
    assert r.primary_class == "out_of_scope"
    assert "candy_cigarette" in r.flags


# Paraphernalia -> out_of_scope, captured with paraphernalia flag (even in tobacco aisle).
PARAPHERNALIA = [
    C("Papel para armar OCB Premium", section="Cigarrillos"),
    C("Encendedor Bic Maxi", section="Cigarrillos"),
    C("Cenicero de vidrio", section="Bazar"),
    C("Filtros para armar 6mm", section="Tabaco"),
]


@pytest.mark.parametrize("item", PARAPHERNALIA)
def test_paraphernalia_demoted_but_tagged(item):
    r = classify_item(item, LEX)
    assert r.primary_class == "out_of_scope", f"{item['name']} should be OOS"
    assert "tobacco_paraphernalia" in r.flags


# --------------------------------------------------------------------------- #
# Plain non-tobacco grocery -> clean out_of_scope, no tobacco flags
# --------------------------------------------------------------------------- #
CLEAN_OOS = [
    C("Coca Cola 1.5L", section="Bebidas"),
    C("Leche Alqueria Entera 1L", section="Lacteos"),
    C("Pan Bimbo Artesano", section="Panaderia"),
]


@pytest.mark.parametrize("item", CLEAN_OOS)
def test_clean_out_of_scope(item):
    r = classify_item(item, LEX)
    assert r.primary_class == "out_of_scope"
    assert not any("context_confirmed" in f or f == "nrt" for f in r.flags)


# --------------------------------------------------------------------------- #
# has_antismoking with no recognizable name -> OOS but flagged for recall review
# --------------------------------------------------------------------------- #
def test_antismoking_unknown_name_is_recall_candidate():
    r = classify_item(C("Producto 18+ misterioso", section="Almacen", antismoking=True), LEX)
    assert r.primary_class == "out_of_scope"
    assert "oos_has_antismoking" in r.flags


@pytest.mark.parametrize("item", [
    C("Waflera Electrica Para Waffles", section="Vaporizadores y dispositivos", antismoking=True),
    C("Revolcon Gel Hiper Acido X12", section="Vaporizadores y dispositivos", antismoking=True),
    C("Bolsa Hermetica 1 Vape", section="Vaporizadores y dispositivos", antismoking=True),
    C("Candela Encendedor B Vape", section="Vaporizadores y dispositivos", antismoking=True),
    C("Candela Soplete Encededor 2 Vape", section="Vaporizadores y dispositivos", antismoking=True),
    C("Guarda Cigarros Plastico Color Rosa", section="Vaporizadores y dispositivos", antismoking=True),
    C("Maquina De Liar Enrolar Armador Cigarrillos", section="Tabaco", antismoking=True),
    C("Raw Tin Pop Box", section="Otros accesorios de cigarrillos", antismoking=True),
])
def test_live_catalog_false_positives_are_demoted(item):
    r = classify_item(item, LEX)
    assert r.primary_class == "out_of_scope", (item, r)


@pytest.mark.parametrize("name", ["Vapes Chillax", "Vapeadores Chillax", "VEEV Now Blue Mint"])
def test_vape_variants_have_product_type(name):
    r = classify_item(C(name, section="Vaporizadores y dispositivos"), LEX)
    assert r.primary_class == "tobacco"
    assert r.product_type == "vape"


# Rolling tobacco must NOT be swallowed by the paraphernalia "armar" family.
def test_rolling_tobacco_not_paraphernalia():
    r = classify_item(C("Tabaco para armar x40g", section="Tabaco"), LEX)
    assert r.primary_class == "tobacco"
    assert r.product_type == "rolling_tobacco"
    assert "tobacco_paraphernalia" not in r.flags


def test_product_identity_precedes_misleading_aisle_type():
    r = classify_item(C("Blunt Wrap X2 Watermelon", section="Vaporizadores y dispositivos"), LEX)
    assert r.primary_class == "tobacco"
    assert r.product_type == "cigar"
