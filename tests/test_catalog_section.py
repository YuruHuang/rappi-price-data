"""Stage C catalog-aisle promotion + universal paraphernalia/hardware demote.

The promotion trusts the store's real aisle (`category_name`, carried as menu_section / the union's
catalog_menu_section) for EITHER source, gated on a genuine tobacco aisle + a positive nicotine signal
+ not-an-accessory. The demote runs on every tobacco row regardless of method.
"""
from rappi_co.classify.stage_c_overrides import apply_overrides
from rappi_co.classify.tobacco_classifier import classify_item, load_market_lexicon


def _oos(name, section, source="catalog", study=False):
    # simulate a Stage-A out_of_scope verdict (name has no lexicon keyword)
    return apply_overrides({"name": name, "menu_section": section, "source": source,
                            "primary_class": "out_of_scope", "flags": []}, study_mode=study)


def _tob(name, section="Cigarrillos", source="crawl", method="keyword_strong", flags=None,
         study=False):
    # simulate a Stage-A tobacco verdict (some keyword promoted it)
    return apply_overrides({"name": name, "menu_section": section, "source": source,
                            "primary_class": "tobacco", "method": method,
                            "flags": list(flags or [])}, study_mode=study)


def _market(name, section, country="ar", **extra):
    """Exercise the complete study classifier, including market-brand context."""
    item = {"name": name, "menu_section": section, **extra}
    stage_a = classify_item(item, load_market_lexicon(country)).as_dict()
    return apply_overrides({**item, **stage_a}, study_mode=True)


def test_promotes_real_nicotine_in_store_tobacco_aisle():
    cases = [
        ("Glucloud Limonada Cerezada Boxpod", "Vaporizadores y dispositivos", "vape_pod"),
        ("Pouches WAKA Citricos 3% - 20pcs", "Vaporizadores y dispositivos", "nicotine_pouch"),
        ("Velo Bolsa de Nicotina Menta 6 mg", "Pouches", "nicotine_pouch"),
        ("Scarlet Iluma Amber", "Cigarrillos", "heated_tobacco"),
    ]
    for name, section, ptype in cases:
        r = _oos(name, section)
        assert r["primary_class"] == "tobacco", name
        assert r["method"] == "catalog_section"
        assert r["product_type"] == ptype, (name, r["product_type"])
        assert "catalog_section" in r["flags"]


def test_new_subtype_inference_is_study_only():
    liquid_legacy = _oos("E Liquid Premium 30ml", "Vaporizadores y dispositivos")
    liquid_study = _oos(
        "E Liquid Premium 30ml", "Vaporizadores y dispositivos", study=True)
    cigar_legacy = _oos("Cigarrillo Cafe Creme Red 20 Unidades", "Cigarrillos")
    cigar_study = _oos(
        "Cigarrillo Cafe Creme Red 20 Unidades", "Cigarrillos", study=True)
    assert liquid_legacy["product_type"] == "vape"
    assert liquid_study["product_type"] == "vape_liquid"
    assert cigar_legacy["product_type"] == "cigarette"
    assert cigar_study["product_type"] == "cigar"


def test_promotes_unbranded_generic_vape_from_search_aisle():
    # search rows carry the product's real category too; a genuine aisle + puff/% signal promotes.
    for name in ("Pod Mijo Mango Ice 15000 Puffs 5%", "Beri 50000 Puffs Watermelon Ice",
                 "Vaper Kokin 10000 Puffs Sandia"):
        r = _oos(name, "Vaporizadores y dispositivos", source="search")
        assert r["primary_class"] == "tobacco", name
        assert r["method"] == "catalog_section"


def test_velo_plural_pouch_types_as_nicotine_pouch():
    r = _oos("VELO Bolsas de Nicotina Fresa 8MG", "Vaporizadores y dispositivos", source="search")
    assert r["primary_class"] == "tobacco"
    assert r["product_type"] == "nicotine_pouch"


def test_keeps_accessories_out_even_in_tobacco_aisle():
    for name in ("Clipper Encendedor Colección Regular", "Glucloud Batería Negra",
                 "Resistencia Coil Vaporesso", "Cargador USB Vape"):
        r = _oos(name, "Vaporizadores y dispositivos")
        assert r["primary_class"] == "out_of_scope", name


def test_accessory_aisle_is_not_a_product_aisle():
    r = _oos("Papel para Armar OCB", "Otros accesorios de cigarrillos")
    assert r["primary_class"] == "out_of_scope"


def test_finished_vape_survives_mis_shelved_accessory_aisle():
    assert _tob("Elfbar Strawberry Spark 40k", "Otros accesorios de cigarrillos")[
        "primary_class"] == "out_of_scope"
    r = _tob("Elfbar Strawberry Spark 40k", "Otros accesorios de cigarrillos", study=True)
    assert r["primary_class"] == "tobacco"


def test_vape_accessory_stays_out_of_scope_in_accessory_aisle():
    for name in ("Estuche para Vape", "Repuesto Pod Vape Vacio"):
        r = _tob(name, "Otros accesorios de cigarrillos", study=True)
        assert r["primary_class"] == "out_of_scope"


def test_complete_vape_kit_is_not_demoted_for_including_a_battery():
    names = (
        "Kit Vape WAKA Creator Dispositivo + Pod + Bateria",
        "Combo Glucloud Pod Uva 4000 Puff + Bateria",
        "Pitahaya Fresca 10.000 Puff - Life Pod 2 Refill + Bateria",
        "Combo Stlth 5k Menta Fresca + Bateria V1 Negra",
        "Stlth Loop 5000 Puffs Kit Bateria + Cartucho",
        "Combo Glucloud Pod Uva 4000 Puff + Battery",
        "Combo Oxbar Battery + Pod Svopp 25K Strawberry Watermelon Peach",
        "Menta Extrema 25.000 Puff - Oxbar Svopp - Extreme Mint + Bateria",
        "Stlth Loop - Pack (bateria + Green Burst) Vape Desechable",
        "Stlth Loop Green Apple + Bateria",
        "Repuesto Loop 5000 Puffs Green Burst",
    )
    for name in names:
        assert _tob(name, study=True)["primary_class"] == "tobacco", name


def test_generic_hardware_packs_are_not_complete_vape_kits():
    names = (
        "Vaporesso Coil Pack X5",
        "Geekvape Resistencia Coil Pack",
        "Vaporesso Battery Pack",
        "Vape Coil Pack",
    )
    for name in names:
        result = apply_overrides({
            "name": name,
            "menu_section": "Vaporizadores y dispositivos",
            "primary_class": "tobacco",
            "product_type": "vape",
            "flags": ["tobacco_paraphernalia"],
        }, study_mode=True)
        assert result["primary_class"] == "out_of_scope", name


def test_misclassified_home_text_vape_bundle_can_be_recovered_from_real_aisle():
    name = "Tabaco Con Tonalidades Dulces 10.000 - Life Pod 2 Refill + Bateria"
    r = _oos(name, "Vaporizadores y dispositivos", study=True)
    assert r["primary_class"] == "tobacco"


def test_tobacco_accessories_and_cannabis_edibles_stay_out():
    for name in ("Cuchara De Tabaco Con Diseño", "Estuche para Tabaco",
                 "Conos Honeypuff X 3", "Gomitas Cannabis 1000 Mg",
                 "Cortador De Cigarros", "Oxbar Svopp Battery"):
        r = _tob(name, study=True)
        assert r["primary_class"] == "out_of_scope", name
    assert _tob("Kit Vape Cannabis Gummies 1000 Mg", study=True)[
        "primary_class"] == "out_of_scope"


def test_standalone_stlth_batteries_stay_out():
    for name in (
        "STLTH Loop Batería V1 para Loop Pod 5K",
        "Stlth Loop 3 Batería",
        "Stlth Loop Batería 3 Vaporizador Electrónico Todo Cartucho Stlth",
        "Stlth Loop - Bateria - Repuesto / Vape Desechable",
    ):
        assert _tob(name, "Vaporizadores y dispositivos", study=True)[
            "primary_class"] == "out_of_scope"


def test_standalone_oxbar_batteries_stay_out_despite_bad_attributes():
    cases = (
        ("Oxbar Batería Svopp Gunmetal",
         '{"puffs": 25000, "vaporizer_type": "Recargable"}'),
        ("Batería Recargable 1100 Mah Para Pod Svopp Oxbar Color Golden | Take A Vape",
         '{"vaporizer_type": "Recargable"}'),
    )
    for name, attributes in cases:
        result = apply_overrides({
            "name": name,
            "menu_section": "Vaporizadores y dispositivos",
            "primary_class": "tobacco",
            "product_type": "vape",
            "attributes_json": attributes,
            "flags": ["contains_paraphernalia"],
        }, study_mode=True)
        assert result["primary_class"] == "out_of_scope", name


def test_standalone_device_bodies_stay_out_but_complete_kits_remain():
    standalone = (
        "Cigarro Device Gold",
        "Stlth Loop Device Black",
        "Stlth Loop 3 Device Vape 25k",
        "Vape Waka Creator Device|Dispositivo",
        "Relx Essential Negro - Vapeador Recargable",
        "Relx Vape Essential Verde",
    )
    for name in standalone:
        result = apply_overrides({
            "name": name,
            "menu_section": "Vaporizadores y dispositivos",
            "primary_class": "tobacco",
            "product_type": "vape",
            "attributes_json": '{"puffs": 25000, "vaporizer_type": "Recargable"}',
            "flags": [],
        }, study_mode=True)
        assert result["primary_class"] == "out_of_scope", name

    for name in (
        "Relx Kit Essential Verde + Pod Sandía 900 Puffs",
        "Vape Kit Waka Creator Dispositivo + Pod Uva 15000 Puffs",
        "Combo Stlth Loop Vape Device + Loop Vape Pod Misty Mango Ice",
    ):
        assert _tob(name, "Vaporizadores y dispositivos", study=True)[
            "primary_class"] == "tobacco", name


def test_standalone_heated_devices_stay_out_but_welcome_kits_and_sticks_remain():
    # Observed titles plus near-miss device titles: any IQOS/ILUMA device/body/kit wording, or a
    # bare IQOS model title, without TEREA/HEETS/stick evidence is hardware, not heated tobacco.
    standalone = (
        "IQOS ILUMA i ONE Azul",
        "Iqos Iluma I Midnigth Black",
        "Iqos Iluma Prime Bronze",
        "ILUMA i One Azul",
        "ILUMA Prime Bronze",
        "Iqos Dispositivo Electrónico de Tabaco Iluma I One Black",
        "Dispositivo Iqos Iluma i One Azul",
        "IQOS Originals Duo Kit Slate",
        "Kit Iqos Iluma One Pebble Grey",
        "Device Iluma i Prime Body Bronze",
        "IQOS Stick Holder",
        "IQOS Sticks Case Black",
        "IQOS Sticks Charger",
        "IQOS HEETS Amber Carrying Case",
        "Combo IQOS ILUMA One Azul",
        "Oferta IQOS ILUMA One Azul",
        "Nuevo IQOS ILUMA Prime Bronze",
    )
    for name in standalone:
        full_pipeline = _market(
            name, "Productos de tabaco calentado", country="mx", has_antismoking=True)
        assert full_pipeline["primary_class"] == "out_of_scope", name
        assert full_pipeline["product_type"] == "heated_device", name
        result = apply_overrides({
            "name": name,
            "menu_section": "Vaporizadores y dispositivos",
            "primary_class": "tobacco",
            "product_type": "heated_tobacco",
            "flags": [],
        }, study_mode=True)
        assert result["primary_class"] == "out_of_scope", name
        assert result["product_type"] == "heated_device", name
        assert "study_heated_device" in result["flags"], name

    retained = (
        "Terea Bronze para IQOS ILUMA",
        "HEETS Green Zing Cajetilla",
        "Iqos Terea Amber Sticks",
        "IQOS Tobacco Sticks 20",
        "Case of 10 HEETS Amber packs for IQOS",
        "Kit de Bienvenida Iqos Iluma One I Mentol",
        "Combo Bienvenida Iqos Iluma One I Clásico",
        "Combo de Bienvenida Iqos Iluma I Cápsulas",
        "Kit Bienvenida Iqos Iluma Prime + Terea Blue",
    )
    for name in retained:
        full_pipeline = _market(
            name, "Productos de tabaco calentado", country="mx", has_antismoking=True)
        assert full_pipeline["primary_class"] == "tobacco", name
        assert full_pipeline["product_type"] == "heated_tobacco", name
        result = apply_overrides({
            "name": name,
            "menu_section": "Filtros",
            "primary_class": "tobacco",
            "product_type": "heated_tobacco",
            "flags": [],
        }, study_mode=True)
        assert result["primary_class"] == "tobacco", name
        assert result["product_type"] == "heated_tobacco", name
        if "bienvenida" in name.lower():
            assert "study_heated_welcome_kit" in result["flags"], name

    # Accessories keep the ordinary paraphernalia route rather than the device subtype.
    charger = _tob("Cargador Iqos Iluma", "Vaporizadores y dispositivos", study=True)
    assert charger["primary_class"] == "out_of_scope"
    assert charger.get("product_type") != "heated_device"


def test_empty_pods_and_ohm_components_stay_out():
    for name in (
        "Cartucho Repuesto Life Pod Eco 3 Pod - (0.6 Ohm)",
        "Xros Pod 0.6 Ohm",
        "Xros Pod 1.2ohm 1.2ohm",
    ):
        assert _tob(name, "Vaporizadores y dispositivos", study=True)[
            "primary_class"] == "out_of_scope", name


def test_dry_herb_and_concentrate_vaporizers_stay_out():
    for name in ("Yocan Kodo Pro", "Vaporizador De Ceras Yocan Orbit",
                 "Vaporizador De Hierba Yocan Hit",
                 "Vaper De Rossin Lookah Mini Unicorn"):
        result = apply_overrides({
            "name": name,
            "menu_section": "Vaporizadores y dispositivos",
            "primary_class": "out_of_scope",
            "attributes_json": '{"vaporizer_type": "Recargable"}',
            "flags": ["oos_section_review"],
        }, study_mode=True)
        assert result["primary_class"] == "out_of_scope", name


def test_vape_flavour_word_gomitas_does_not_demote_a_finished_vape():
    name = "Vape Airfuze Smart 30k Puffs - Sour Gummy (gomitas Frutales Acidas)"
    assert _tob(name, "Vaporizadores y dispositivos", study=True)[
        "primary_class"] == "tobacco"


def test_study_cosmetic_and_liquid_dispenser_collisions_stay_out():
    cosmetic = "Autobronceador Glow Your Own Way - B.tan Self Tan Gel 437ml"
    assert _tob(cosmetic, "Vaporizadores y dispositivos", study=True)[
        "primary_class"] == "out_of_scope"
    dispenser = "Dispensador Para Endulzante Liquido"
    assert _oos(dispenser, "Vaporizadores y dispositivos", study=True)[
        "primary_class"] == "out_of_scope"


def test_study_search_collisions_stay_out():
    names = (
        "Box Chelero Alianza Lima",
        "Gift Box Mateo",
        "Guia Practica De Astrologia Deluxe Box Set",
        "Vape Insecticida Aparato + 5 Pastillas Mata al Mosquito",
        "Vape Plaguicida de Uso Domestico",
        "Magic Box Vibrating Egg Gold",
        "Bang 28x Power Panty Remote Control Bullet Kit",
        "Redken Aclarador Interior Flash Lift Pods",
        "Bebida Drink Zyn Mango Litchi 355 ml",
        "Combo Velo Green Spearmint + Carta Blanca Caguamita 6 Und",
        "Combo Hielo Club + Zyn Cool Mint (6 mg)",
        "Voopoo Pnp-vm1 0.3ohm",
        "Voopoo Tanque Pnp Mesh 0.15Ohm",
    )
    for name in names:
        assert _tob(name, "Cigarrillos", study=True)["primary_class"] == "out_of_scope", name


def test_study_edible_and_homeware_collisions_stay_out():
    # Gummy/edible titles with an mg dose and no independent vape identity stay out, whether
    # they arrive as Stage-A tobacco or as an aisle-promotion candidate.
    for name in (
        "Gomas Mágica Double Starked Bitez | Green Apple Watermelon 2000mg",
        "Goma Magica Vape Kit Pod 2000mg",
        "Gomas Bitez Green Apple 2000mg",
        "Gomitas Con Magic Green Blue Moon | 1000 Mg Sabor Wild Blueberry 2und",
        "Gummies Delta Rainbow 1000mg",
        "Gummy Liquid Drops 1000mg",
        "Gummy Device Drops 1000mg",
        "Gomitas Magicas Sour Watermelon X10und",
    ):
        edible = apply_overrides({
            "name": name,
            "menu_section": "Vaporizadores y dispositivos",
            "primary_class": "out_of_scope",
            "flags": ["oos_section_review"],
        }, study_mode=True)
        assert edible["primary_class"] == "out_of_scope", name
        promoted = _tob(name, "Vaporizadores y dispositivos", study=True)
        assert promoted["primary_class"] == "out_of_scope", name
        assert _market(name, "Vaporizadores y dispositivos", country="co")[
            "primary_class"] == "out_of_scope", name

    # Context-required brand + homeware/dishware title without any product evidence is out.
    for name in ("Bowl Jaspeado Camel", "Bowl Camel", "Plato Jaspeado Camel",
                 "Camel XL Mug 20", "Bowl Camel Box 20", "Plato Camel 12",
                 "Taza Ceramica Kent", "Taza Kent Light", "Cortina Master Beige"):
        country = "pe" if "Kent" in name else "ar"
        full_pipeline = _market(
            name, "Cigarrillos", country=country, has_antismoking=True)
        assert full_pipeline["primary_class"] == "out_of_scope", name
        assert "study_homeware_collision" in full_pipeline["flags"], name
        homeware = apply_overrides({
            "name": name,
            "menu_section": "Cigarrillos",
            "primary_class": "tobacco",
            "product_type": "cigarette",
            "method": "keyword_context_confirmed",
            "has_antismoking": True,
            "flags": ["context_confirmed:section"],
        }, study_mode=True)
        assert homeware["primary_class"] == "out_of_scope", name
        assert "study_homeware_collision" in homeware["flags"], name

    # Real context-brand products keep their verdict: product evidence in the title wins.
    for name in ("Camel Box 20", "Camel Activate Caja", "Camel Comun 20", "Kiel Box",
                 "Red Point Comun", "Master Cigarillos Filter", "Velo Pouch de Nicotina 4 mg"):
        real = apply_overrides({
            "name": name,
            "menu_section": "Cigarrillos",
            "primary_class": "tobacco",
            "product_type": "cigarette",
            "method": "keyword_context_confirmed",
            "has_antismoking": True,
            "flags": ["context_confirmed:section"],
        }, study_mode=True)
        assert real["primary_class"] == "tobacco", name

    # Gummy-flavour vapes keep their vape identity (puffs, k capacity, vape/pod words, brands).
    for name in (
        "Vape Airfuze Smart 30k Puffs - Sour Gummy (gomitas Frutales Acidas)",
        "Vapeador Swedish Gummy Vera 22.000 Puffs",
        "Vape/ Vaporizador Hulk Hogan - White Gummy - 8k",
        "Vape Kit Pod Sabor Gomita 20mg 5000 Puffs",
    ):
        real_vape = _oos(name, "Vaporizadores y dispositivos", study=True)
        assert real_vape["primary_class"] == "tobacco", name
        assert str(real_vape["product_type"]).startswith("vape"), name


def test_tobacco_tab_pouches_stay_out_of_nicotine_pouch_family():
    # Snus / tobacco 'tab pouch' titles are smokeless tobacco unless the title itself says the
    # product is a tobacco-free nicotine pouch.
    for name in (
        "Odens Tab Pouches 1510200 Cold Dry 22mg X10gr",
        "Siberia Tab Pouches 1510120 X-tremely Blue White Spearmint 25mg X15gr",
        "Vika Tab Pouches 1530200 Black White Dry Mint Strong 28mg X13gr",
        "General Snus White Portion",
        "Odens Cold Dry Snus 10g",
        "Siberia Snus -80 Degrees",
        "Thunder Tobacco Pouches Frosted 16g",
    ):
        result = apply_overrides({
            "name": name,
            "menu_section": "Pouches",
            "primary_class": "tobacco",
            "product_type": "nicotine_pouch",
            "attributes_json": '{"is_pod": true, "puffs": 200}',
            "flags": [],
        }, study_mode=True)
        assert result["primary_class"] == "tobacco", name
        assert result["product_type"] == "smokeless_tobacco", name
        assert "study_tobacco_pouch" in result["flags"], name

    for name in (
        "Vika Nic Pouches 1530115 Blueberry Cosmo 12mg X12gr",
        "Velo Snus-style Nicotine Pouches sin tabaco 6mg",
        "Zyn Snus Tobacco-Free Nicotine Pouches Cool Mint 6mg",
        "Bagz Nic Pouches Apple Ice 8mg X15.10gr",
    ):
        nicotine_pouch = apply_overrides({
            "name": name,
            "menu_section": "Pouches",
            "primary_class": "tobacco",
            "product_type": "nicotine_pouch",
            "flags": [],
        }, study_mode=True)
        assert nicotine_pouch["primary_class"] == "tobacco", name
        assert nicotine_pouch["product_type"] == "nicotine_pouch", name

    explicit_vapes = {
        "E-liquid sabor Snus 30ml": "vape_liquid",
        "Snus Disposable 10000 Puffs": "vape_disposable",
        "Vape sabor Snus 5%": "vape",
    }
    for name, product_type in explicit_vapes.items():
        result = _market(name, "Vaporizadores y dispositivos", country="pe")
        assert result["primary_class"] == "tobacco", name
        assert result["product_type"] == product_type, name
        assert "study_snus_vape_identity" in result["flags"], name


def test_cannabinoid_disposables_stay_out_of_the_nicotine_study():
    names = (
        "Vape Dozo Torch Disposable 2.5 Gr Sati Pineapple Fruz",
        "Vape Half Bakd Sumo Disposable 5gr Indi Especial",
        "Vape Packman Switch 2gr Blue Hybr",
        "Vape Escobars 3grms P.k.o Indic",
        "Vape Mag Elf Th 1gr Original",
        "Vape Fume Delta 8 Rainbow Belts Indi 2ml",
    )
    for name in names:
        assert _tob(name, "Vaporizadores y dispositivos", study=True)[
            "primary_class"] == "out_of_scope", name


def test_study_promotes_observed_vape_capacity_spellings_from_vape_aisle():
    names = (
        "Death Row 7.000 Pufs Black Ice 5%",
        "Menta Fresca Divi 10000 Aspiraciones 5% 50mg",
        "Mint 3k",
        "Spaceman Sp50000 Strawberry Watermelon",
        "Litpod Switch Kit Frozen Blueberry",
    )
    for name in names:
        result = _oos(name, "Vaporizadores y dispositivos", study=True)
        assert result["primary_class"] == "tobacco", name
        assert str(result["product_type"]).startswith("vape"), name


def test_antismoking_vaporizador_needs_a_product_level_study_signal():
    def classify(name):
        return apply_overrides({
            "name": name,
            "menu_section": "Vaporizadores y dispositivos",
            "primary_class": "out_of_scope",
            "has_antismoking": True,
            "flags": ["oos_section_review"],
        }, study_mode=True)

    vape = classify("Krew Vaporizador 700 Puff Strawberry Mango")
    assert vape["primary_class"] == "tobacco"
    assert vape["product_type"] == "vape_disposable"
    iberia = apply_overrides({
        "name": "Iberia Vaporizador",
        "menu_section": "Vaporizadores y dispositivos",
        "primary_class": "out_of_scope",
        "has_antismoking": True,
        "attributes_json": '{"vaporizer_type": "Recargable"}',
        "flags": ["oos_section_review"],
    }, study_mode=True)
    assert iberia["primary_class"] == "out_of_scope"
    assert classify("Vaporizador Liquid Diamond 5gr Runtz Indi")[
        "primary_class"] == "out_of_scope"


def test_finished_vape_can_describe_its_integrated_dual_mesh_coil():
    result = apply_overrides({
        "name": "Vape Fume Pro 30k Puffs 5% Dual Mesh Coil Strawberry",
        "menu_section": "Vaporizadores y dispositivos",
        "primary_class": "tobacco",
        "product_type": "vape",
        "flags": [],
    }, study_mode=True)
    assert result["primary_class"] == "tobacco"


def test_finished_vape_coil_and_battery_kits_can_recover_from_stage_a_floor():
    names = (
        "Vape Fume Pro 30k Puffs 5% Dual Mesh Coil Strawberry",
        "Combo Oxbar Battery + Pod Svopp 25K Grapefruit Passion Fruit",
    )
    for name in names:
        result = apply_overrides({
            "name": name,
            "menu_section": "Vaporizadores y dispositivos",
            "primary_class": "out_of_scope",
            "product_type": "vape",
            "flags": ["tobacco_paraphernalia"],
        }, study_mode=True)
        assert result["primary_class"] == "tobacco", name


def test_integrated_coil_does_not_override_cannabinoid_exclusion():
    result = apply_overrides({
        "name": "Vape THC 30000 Puffs Dual Mesh Coil",
        "menu_section": "Vaporizadores y dispositivos",
        "primary_class": "tobacco",
        "product_type": "vape",
        "flags": ["tobacco_paraphernalia"],
    }, study_mode=True)
    assert result["primary_class"] == "out_of_scope"


def test_structured_and_advertised_finished_vapes_are_recovered():
    cases = (
        ("Oxbar Svopp 35k Pod Grape Ice - Repuesto",
         '{"is_pod": true, "puffs": 35000, "vaporizer_type": "Desechable"}'),
        ("Sea Bear S2 - 3500", '{"puffs": 3500, "vaporizer_type": "Desechable"}'),
        ("Dragbar 3500 Strawberry Ice Cream",
         '{"puffs": 3500, "vaporizer_type": "Desechable"}'),
        ("Virginia Tobacco - 50mg",
         '{"is_pod": true, "vaporizer_type": "Desechable"}'),
        ("Nexa N20000 Kiwi Pineapple", ""),
    )
    for name, attributes in cases:
        result = apply_overrides({
            "name": name,
            "menu_section": "Vaporizadores y dispositivos",
            "primary_class": "out_of_scope",
            "attributes_json": attributes,
            "flags": ["oos_section_review"],
        }, study_mode=True)
        assert result["primary_class"] == "tobacco", name
        assert str(result["product_type"]).startswith("vape"), name


def test_structured_vape_attributes_require_independent_name_evidence():
    unrelated = apply_overrides({
        "name": "Sidelines Mango Eco Con Bozales Rosetta Negro S200",
        "menu_section": "Vaporizadores y dispositivos",
        "primary_class": "out_of_scope",
        "attributes_json": '{"puffs": 200, "vaporizer_type": "Desechable"}',
        "flags": ["oos_section_review"],
    }, study_mode=True)
    assert unrelated["primary_class"] == "out_of_scope"


def test_bad_structured_attributes_do_not_change_pouch_or_heated_identity():
    cases = (
        ("Zyn Cereza Negra 6 mg Pouches", "nicotine_pouch"),
        ("Zyn Cool Mint 6mg", "nicotine_pouch"),
        ("6x Zyn Cool Mint 6mg", "nicotine_pouch"),
        ("Velo Polar Mint Bolsa de Nicotina 10 mg", "nicotine_pouch"),
        ("Terea Bronze para IQOS ILUMA", "heated_tobacco"),
    )
    for name, product_type in cases:
        result = apply_overrides({
            "name": name,
            "menu_section": "Vaporizadores y dispositivos",
            "primary_class": "tobacco",
            "product_type": product_type,
            "attributes_json": '{"puffs": 200, "vaporizer_type": "Desechable"}',
            "flags": [],
        }, study_mode=True)
        assert result["primary_class"] == "tobacco", name
        assert result["product_type"] == product_type, name


def test_explicit_puffs_recover_mis_shelved_finished_vape():
    for name, section in (
        ("Dinnerlady Cig Elect 1500 Puff Lemon Mojito", "Otros accesorios de cigarrillos"),
        ("Esencia Fume Nb-super-p 20.000 Puffs Strawberry Banana",
         "Otros Accesorios de Tecnología"),
        ("Pod Mijo Ron Con Pasas 15000 Puffs 5%", "Otros Accesorios de Tecnología"),
        ("Vaporizador Con Boquilla Recargable 5000 Puff",
         "Vaporizadores y dispositivos"),
    ):
        result = apply_overrides({
            "name": name,
            "menu_section": section,
            "primary_class": "out_of_scope",
            "flags": ["tobacco_paraphernalia"],
        }, study_mode=True)
        assert result["primary_class"] == "tobacco", name
        assert str(result["product_type"]).startswith("vape"), name


def test_vape_shop_capacity_recovers_mis_shelved_flavour_title():
    result = apply_overrides({
        "name": "Watermelon Ice 15k",
        "store_name": "Vapershito Candy",
        "menu_section": "Galletas",
        "primary_class": "out_of_scope",
        "flags": [],
    }, study_mode=True)
    assert result["primary_class"] == "tobacco"
    assert result["product_type"] == "vape_disposable"


def test_verified_vape_retail_prefix_recovers_truncated_flavour_title():
    result = apply_overrides({
        "name": "Sour Peach Pineapple Ic",
        "store_name": "Vapershito Candy",
        "retail_id": "VpPolanquirriMCmt_SourPeachPineappleIc",
        "menu_section": "Galletas",
        "primary_class": "out_of_scope",
        "flags": [],
    }, study_mode=True)
    assert result["primary_class"] == "tobacco"
    assert result["product_type"] == "vape_disposable"
    assert result["rationale"] == "reviewed vape retailer SKU identity"

    unverified = apply_overrides({
        "name": "Sour Peach Pineapple Ic",
        "store_name": "Vapershito Candy",
        "retail_id": "ordinary-cookie-sku",
        "menu_section": "Galletas",
        "primary_class": "out_of_scope",
        "flags": [],
    }, study_mode=True)
    assert unverified["primary_class"] == "out_of_scope"


def test_structured_recargable_liquids_recover_from_vape_aisle():
    for name, attributes in (
        ("V2 Liquido Vainilla 0 X 10ml", '{"vaporizer_type": "Recargable"}'),
        ("Vgod Liquido Iced Berry Bomb X60ml 03mg",
         '{"vaporizer_type": "Recargable"}'),
        ("Skwezed Blankers Ice 10ml Kit Pineapple 25mg", ""),
    ):
        result = apply_overrides({
            "name": name,
            "menu_section": "Vaporizadores y dispositivos",
            "primary_class": "out_of_scope",
            "has_antismoking": True,
            "attributes_json": attributes,
            "flags": ["oos_section_review"],
        }, study_mode=True)
        assert result["primary_class"] == "tobacco", name
        assert result["product_type"] == "vape_liquid", name


def test_v2_liquid_titles_recover_without_trusting_generic_volume_alone():
    for name in (
        "V2 Liquido Red 0 X10ml",
        "V2 Liquido Green Tea Menthol 6X10Ml",
    ):
        result = _oos(name, "Vaporizadores y dispositivos", study=True)
        assert result["primary_class"] == "tobacco", name
        assert result["product_type"] == "vape_liquid", name

    for name in ("V2 Green Tea Menthol 6X10Ml", "Serum Hidratante 6X10Ml"):
        assert _oos(name, "Vaporizadores y dispositivos", study=True)[
            "primary_class"] == "out_of_scope", name


def test_new_product_boundaries_are_study_only():
    cases = (
        ("Iqos Iluma Prime Bronze", "heated_tobacco"),
        ("Vika Tab Pouches 1530200 Black White Dry Mint Strong 28mg X13gr",
         "nicotine_pouch"),
    )
    for name, product_type in cases:
        result = apply_overrides({
            "name": name,
            "menu_section": "Cigarrillos",
            "primary_class": "tobacco",
            "product_type": product_type,
            "flags": [],
        })
        assert result["primary_class"] == "tobacco", name
        assert result["product_type"] == product_type, name


def test_antismoking_warning_recovers_unbranded_cigarette():
    for name in ("Royal 20Un", "American Spirit Azul"):
        result = apply_overrides({
            "name": name,
            "menu_section": "Cigarrillos",
            "primary_class": "out_of_scope",
            "has_antismoking": True,
            "flags": ["oos_section_review"],
        }, study_mode=True)
        assert result["primary_class"] == "tobacco"
        assert result["product_type"] == "cigarette"


def test_explicit_puff_capacity_corrects_noisy_cigarette_subtype():
    for name in (
        "Fume Pro 30k Mango Tango",
        "Oxbar Dualblend 50k Kit Banana and Blackberry Melon",
        "Vice Box 6000puff Blue Raspberry Ice",
        "Nexa Flex Kit Watermelon Ice 25k",
    ):
        result = apply_overrides({
            "name": name,
            "menu_section": "Cigarrillos",
            "primary_class": "tobacco",
            "product_type": "cigarette",
            "flags": [],
        }, study_mode=True)
        assert result["product_type"] == "vape_disposable", name


def test_cigar_identity_wins_when_recovered_from_cigarette_aisle():
    for name in ("Puro Cafe Creme Red 20 Unidades",
                 "Puros Montecristo Open Eagle X 3 Und",
                 "Puritos Partagas Serie X 5 Und"):
        result = apply_overrides({
            "name": name,
            "menu_section": "Cigarrillos",
            "primary_class": "out_of_scope",
            "has_antismoking": True,
            "flags": ["oos_section_review"],
        }, study_mode=True)
        assert result["primary_class"] == "tobacco", name
        assert result["product_type"] == "cigar", name


def test_bare_puff_or_ml_is_not_enough_for_aisle_promotion():
    for name in ("Puff Crema Facial", "Serum Hidratante 30 ml"):
        r = _oos(name, "Vaporizadores y dispositivos", study=True)
        assert r["primary_class"] == "out_of_scope", name


def test_mg_dose_in_true_pouch_aisle_is_promoted_in_study_mode():
    r = _oos("Cool Mint Flavor 12 Mg", "Pouches", study=True)
    assert r["primary_class"] == "tobacco"
    assert r["product_type"] == "nicotine_pouch"


def test_gram_denominated_cigarette_title_is_routed_to_loose_tobacco():
    r = apply_overrides({
        "name": "Luckies Tabaco Original",
        "menu_section": "Cigarrillos",
        "primary_class": "tobacco",
        "product_type": "cigarette",
        "unit_price_unit": "g",
        "pack_format_raw": "1 x 30 g",
        "flags": [],
    }, study_mode=True)
    assert r["product_type"] == "rolling_tobacco"
    assert "study_weighted_loose_tobacco" in r["flags"]


def test_explicit_unit_sold_cigarette_suffix_beats_bad_gram_metadata():
    unit_sold = apply_overrides({
        "name": "Camel Tabaco Filters Original 25S",
        "menu_section": "Cigarrillos",
        "primary_class": "tobacco",
        "product_type": "cigarette",
        "unit_price_unit": "g",
        "pack_format_raw": "1 x 29 g",
        "sale_type": "U",
        "flags": [],
    }, study_mode=True)
    weighted = apply_overrides({
        "name": "Winston Red 20's",
        "menu_section": "Cigarrillos",
        "primary_class": "tobacco",
        "product_type": "cigarette",
        "unit_price_unit": "g",
        "pack_format_raw": "25g",
        "sale_type": "WP",
        "flags": [],
    }, study_mode=True)
    lucky = apply_overrides({
        "name": "Lucky Strike Mora 10 Unidades",
        "menu_section": "Cigarrillos",
        "primary_class": "tobacco",
        "product_type": "cigarette",
        "unit_price_unit": "g",
        "pack_format_raw": "1mg",
        "flags": [],
    }, study_mode=True)
    assert unit_sold["product_type"] == "cigarette"
    assert weighted["product_type"] == "cigarette"
    assert lucky["product_type"] == "cigarette"


def test_nicotine_free_herbal_wrap_not_promoted():
    # explicit tobacco/nicotine-free herbal wrap in a Cigarrillos aisle must stay out.
    r = apply_overrides({"name": "Hemp Zone Rillo Size Mango 5 Herbal Wraps tobacco & Nicotine Free",
                         "menu_section": "Cigarrillos", "source": "catalog",
                         "primary_class": "out_of_scope", "flags": ["non_nicotine_herbal"]})
    assert r["primary_class"] == "out_of_scope"


def test_search_no_nicotine_signal_not_promoted():
    # the 'tabaco' search-bucket false-positive class (paint/wood/food) has no nicotine signal.
    for name in ("Tabaco Exterior", "Mesa Madeira Tabaco", "Vela Aroma Tabaco y Cuero"):
        r = _oos(name, "Cigarrillos", source="search")
        assert r["primary_class"] == "out_of_scope", name


def test_universal_demote_blunt_wraps_and_papers():
    # empty rolling material promoted by Stage A keyword_strong 'blunt' -> out_of_scope, any method.
    for name in ("Combo Blunt Wrap + Circus Terpenos", "Blunt Wrap X4 Strawberry",
                 "Papel Cueros # 12 50 Cajas De Blunt Black King Size", "Combo Papeles Y Blunt",
                 "The Original Blunt Wrap Hemp Chocolate 4 Wraps Per Pack"):
        r = _tob(name)
        assert r["primary_class"] == "out_of_scope", name
        assert "nontobacco_demote" in r["flags"], name


def test_universal_demote_vape_hardware():
    for name in ("Bateria Vape WAKA CREATOR Negra", "Batería Awt 18650 Para Vape",
                 "Glucloud Batería Box Pod", "Honey Stick Box Concealer 510 - Batería - Blue"):
        r = _tob(name, section="Vaporizadores y dispositivos")
        assert r["primary_class"] == "out_of_scope", name


def test_universal_demote_pipe_device_but_keep_pipe_tobacco():
    assert _tob("Pipa Metal Cigarrillo")["primary_class"] == "out_of_scope"
    assert _tob("Pipa Hoja Vape")["primary_class"] == "out_of_scope"
    # real pipe tobacco asserts 'tabaco' in the name -> stays in scope.
    assert _tob("Tabaco para Pipa Amsterdamer Original")["primary_class"] == "tobacco"


def test_universal_demote_rolling_machine_and_accessory_aisle():
    assert _tob("Rolling Machine Raw Hemp Plastic Roller 79mm")["primary_class"] == "out_of_scope"
    assert _tob("Maquina Para Armar Cigarrillos",
                section="Otros accesorios de cigarrillos")["primary_class"] == "out_of_scope"
