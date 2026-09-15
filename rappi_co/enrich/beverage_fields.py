"""Conservative, offline beverage classification and explicit-label extraction.

``enrich_beverage(row)`` returns an enrichment dict; it does not mutate ``row``.
Inputs: name, short_description, product_information (plain product-detail text),
ingredients_text, nutrition_text, attributes_json (JSON/dict/list),
pack_format_raw, quantity/unit_type, and explicit volume_per_unit_ml. Legacy
volume_ml/pack_count are preserved as unverified evidence only. Category is water, ssb, alcohol, non_ssb, review,
or excluded. An SSB requires evidence of added sugar/sweetening; total sugar in
juice alone is insufficient. Zero/diet claims are comparison non_ssb rows, never
numeric zero. A generic soda/juice/energy drink with unknown sugar is review.

Numeric outputs: volume_per_unit_ml, pack_count, total_volume_ml,
sugar_g_per_100ml, sugar_g_per_serving, serving_volume_ml, abv_pct. Each has
``<field>_source`` and ``<field>_evidence``. ``beverage_evidence_json`` retains all
candidate facts with original source text, including unresolved conflicts.
``beverage_flags`` is a sorted list. Conflicting values are blanked, not silently
ranked. Counts require explicit package evidence; unknown count is not one.
Total volume and normalized sugar may be calculated only from explicit operands
and are marked ``derived:...``. Ambiguous/mixed bundles are retained for review
with package and composition fields blank. This first pass does not read images,
infer branded nutrition, interpret carbohydrates as sugar, or read bare percent
values as ABV. Numeric units in structured attribute keys are explicit evidence.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from typing import Any

_FIELDS = ("volume_per_unit_ml", "pack_count", "total_volume_ml",
           "sugar_g_per_100ml", "sugar_g_per_serving", "serving_volume_ml", "abv_pct")
_NUM = r"(?<![\d.,])\d+(?:[.,]\d+)?"
_UNIT = r"(?:mililitros?|ml|cc|cm3|cm³|cmq|centilitros?|cl|litros?|lts?|l)\b"
_VOL = re.compile(rf"(?P<n>{_NUM})\s*(?P<u>{_UNIT})")
_SUGAR = r"(?:azucar(?:es)?\b|sugars?\b|acucar(?:es)?\b)"
_ADDED = r"(?:anadidos?|agregados?|adicionados?|added)"
_SERVING = r"(?:porcion(?:es)?|porcao|servings?)"
_FAMILY = {
    "beer": r"\b(?:cervezas?|beer|cervejas?|birras?)\b",
    "wine": r"\b(?:vinos?|wine|espumantes?|champagne|champana|sidras?|jerez|vermu(?:t|th))\b",
    "spirits": r"\b(?:aguardiente|whisk[ey]+|vodka|ron|rum|tequila|mezcal|pisco|gin|ginebra|cachaca|brandy|conac|cognac|licor(?:es)?|fernet)\b",
    "cocktail": r"\b(?:coctel(?:es)?|cocktails?|hard seltzer|bebida alcoholica|sangria|clerico)\b",
    "aperitif": r"\baperitivo\b",
    "soft_drink": r"\b(?:gaseosas?|refrescos?|refrigerantes?|soda|[ck]ola|tonica|ginger ale)\b",
    "energy_drink": r"\b(?:energizantes?|energeticas?|energy drink)\b",
    "sports_drink": r"\b(?:isotonicas?|isotonicos?|bebida deportiva|sports drink|(?:re)?hidratantes?)\b",
    "juice": r"\b(?:jugos?|zumos?|nectar(?:es)?|suco|refresco de fruta)\b",
    "tea_coffee": r"\b(?:te|tea|cafe|coffee|mate|terere|capu(?:c|cc)h?ino|cappuccino|latte|frappuccino)\b",
    "dairy_beverage": r"\b(?:leche|bebida lactea|chocolatada|batido|licuado|malteadas?|milkshake|mcshake|yogur bebible|chocolate (?:caliente|frio))\b",
    "flavored_water": r"\bagua\s+(?:saborizada|saborisada|saborizada|sabor|de coco|de fruta|de jamaica|de horchata|de panela|tonica)\b|\baguapanela\b",
    "water": r"\b(?:aguas?|aguitas?|waters?|seltzer)\b",
    "other_beverage": r"\b(?:bebidas?|drink|limonada|lemonade|horchata|chicha|kombucha|smoothies?)\b",
}
# These are platform attribute *types*, not brand dictionaries or search terms.
# Generic flavor/packaging/volume keys never establish a beverage on their own.
_TYPED_FAMILY = {
    "soda_type": "soft_drink", "colas_o_sabores": "soft_drink",
    "flavor_energy_drinks": "energy_drink", "isotonic_flavor": "sports_drink",
    "flavor_juices": "juice", "nectars_flavor": "juice",
    "ready_tea_flavor": "tea_coffee", "flavored_water_flavor": "flavored_water",
    "cereal_drinks_flavor": "other_beverage", "dairy_drinks_classification": "dairy_beverage",
    "flavored_milk_flavor": "dairy_beverage", "vegetal_milk_type": "other_beverage",
    "beer_style": "beer", "varietal_wine": "wine", "wine_type": "wine", "cider_type": "wine",
    "rum_type": "spirits", "pisco_type": "spirits", "vodka_flavor": "spirits", "gin_style": "spirits",
    "whisky_blend_variant": "spirits", "aguardiente_label_color": "spirits",
    "segmento_tequila": "spirits", "segmento_mezcal": "spirits",
    "flavor_cream_liqueur": "spirits", "liquor_type": "spirits",
}
_ALCOHOL = {"beer", "wine", "spirits", "cocktail"}
_WATER_MODIFIERS = re.compile(
    r"\bsabor|\b(?:funcional|inulina|aloe|limonada|coco|azahar|floral|"
    r"proteins?|proteinas?|vitamins?|vitaminas?|collagen|colageno|electrolytes?|"
    r"electrolitos?|infused|infusionada|frescas?|limon|lima|jamaica|pina|naranja|"
    r"manzana|mango|fresa|frutilla|durazno|melocoton|maracuya|uvas?|toronja|pomelo|pera|arandanos?|gulupa|"
    r"tamarindo|chia|hierbabuena|menta|jengibre|pepino|sandia|melon|guayaba|guanabana|"
    r"lulo|cereza|avena|mamey|papaya|horchata|lemon|lime|mint|berry|orange|peach|"
    r"lemonade|citrus)(?=\b|\d)")
_EXCLUDE = re.compile(
    r"\b(?:agua (?:oxigenada|micelar|destilada|desmineralizada|de colonia)|alcohol (?:etilico|antiseptico|isopropilico|en gel)|"
    r"agua de rosas|mascotas|gasificadora|cilindro|desinfectante|gel antibacterial|perfume|shampoo|champu|detergente|limpiador|"
    r"vasos?|copas?|abridor|destapador|sacacorchos|botella vacia|envase para agua|dispensador|paletas?|ice[ -]?pop|popsicle|hielo|gel(?:es)?|"
    r"jarabe|sirope|concentrado|bebida conc|base (?:de|para) (?:coctel|cocktail|bebidas?)|deshidratad[oa]s?|polvo|capsulas?|te en (?:bolsas|saquitos)|cafe (?:molido|en grano|instantaneo)|"
    r"galletas?|chocolates?|helados?|caramelos?|gomitas?|salsa|vinagre)\b")
_NO_ADDED_SUGAR = re.compile(r"\b(?:sin azucar(?:es)? (?:anadid[oa]s?|agregad[oa]s?|adicionad[oa]s?)|no added sugars?)\b")
_NO_SUGAR = re.compile(r"\b(?:sin azucar(?:es)?\b(?!\s+(?:anadid|agregad|adicionad))|"
                       r"sem acucar|zero sugar|sugar free|sugar-free|"
                       r"cero azucar|0\s*%\s*(?:de\s+)?azucar|zero|diet(?:etica|etico)?)\b")
_UNSWEETENED = re.compile(r"\b(?:sin endulzar|no endulzado|unsweetened|nao adocado|sem adocante)\b")
_SWEETENED = re.compile(r"\b(?:endulzad[oa] con (?:azucar|panela|miel)|con azucar|con panela|"
                       r"adocad[oa] com acucar|sugar sweetened)\b")
_NON_ALCOHOL = re.compile(r"\b(?:sin alco(?:h|ch)ol|cero alcohol|sem alcool|non[ -]alcoholic|non alcoh|alcohol free)\b")


def _fold(value: Any) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(value)).lower()
                   if not unicodedata.combining(c))


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace(",", "."))
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _ml(number: str, unit: str) -> float:
    value = float(number.replace(",", "."))
    if unit.startswith("cl") or unit.startswith("centilitro"):
        value *= 10
    elif unit.startswith("l"):
        value *= 1000
    return value


def _attributes(value: Any, path="attributes_json"):
    """Preserve attribute paths; pair label/value objects instead of losing labels."""
    if isinstance(value, str) and path == "attributes_json":
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            yield path, value
            return
    if isinstance(value, dict):
        label = value.get("name") or value.get("label") or value.get("title")
        payload = value.get("value")
        if payload is not None and not isinstance(payload, (dict, list)) and (label or path != "attributes_json"):
            # Some suppliers put the label on the enclosing key instead of in
            # the value object. Preserve that key and its unit in the evidence.
            attribute_path = f"{path}.{label}" if label else path
            label = label or path.rsplit(".", 1)[-1]
            yield attribute_path, f"{label}: {payload} {value.get('unit', '')}".strip()
        else:
            for key, child in value.items():
                yield from _attributes(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _attributes(child, f"{path}[{index}]")
    elif value is not None:
        yield path, str(value)


def _sources(row: dict) -> list[tuple[str, str]]:
    result = [(key, str(row[key])) for key in
              ("name", "short_description", "product_information", "pack_format_raw", "nutrition_text")
              if row.get(key) is not None and str(row[key]).strip()
              and str(row[key]).lower() != "nan"]
    result.extend(_attributes(row.get("attributes_json")))
    if row.get("ingredients_text"):
        result.append(("ingredients_text", "Ingredientes: " + str(row["ingredients_text"])))
    if row.get("quantity") not in (None, "") and re.fullmatch(_UNIT, _fold(row.get("unit_type") or "")):
        result.append(("listing.quantity/unit_type", f"{row['quantity']} {row['unit_type']}"))
    return result


def _extract_facts(sources, row, flags):
    facts = []

    def add(field, value, source, evidence, raw):
        value = _number(value)
        upper = {"abv_pct": 100, "pack_count": 1000,
                 "sugar_g_per_100ml": 100, "sugar_g_per_serving": 1000}.get(field, 1_000_000)
        if value is None or value < 0 or value > upper or (value == 0 and "sugar" not in field and field != "abv_pct"):
            flags.add(f"invalid_{field}")
            return
        if field == "pack_count":
            if not value.is_integer():
                flags.add("invalid_pack_count")
                return
            value = int(value)
        fact = dict(field=field, value=value, source=source, evidence=evidence, raw_text=raw)
        if fact not in facts:
            facts.append(fact)

    # Only the new normalized field has an explicit guarantee. Legacy fields may
    # have been guessed from presentation punctuation/count placeholders.
    for field in ("volume_per_unit_ml",):
        if row.get(field) not in (None, ""):
            add(field, row[field], f"listing.{field}", str(row[field]), str(row[field]))
    for field in ("volume_ml", "pack_count"):
        if row.get(field) not in (None, ""):
            facts.append(dict(field="unverified_legacy_" + field, value=row[field],
                              source="listing." + field, evidence=str(row[field]), raw_text=str(row[field])))

    for source, raw in sources:
        text = _fold(raw)
        # Unit-bearing structured keys are accepted without guessing bare numbers.
        attr_key = _fold(source.split(".")[-1]).replace(" ", "_")
        # These supplier aliases preserve the same explicit ABV/count semantics;
        # the original path remains the evidence source. Volume aliases already
        # carry their own mL/L text and need no implicit unit conversion.
        attr_key = {"pps_abv": "abv", "pps_pack_size": "pack_size",
                    "units_per_pack": "pack_count"}.get(attr_key, attr_key)
        attr_value = text.split(":", 1)[-1].strip() if ":" in text else text.strip()
        if source.startswith("attributes_json") and attr_key in _FIELDS:
            expected_unit = (r"(?:ml)?" if attr_key in {"volume_per_unit_ml", "total_volume_ml", "serving_volume_ml"}
                             else r"(?:%)?" if attr_key == "abv_pct"
                             else r"(?:g)?" if "sugar" in attr_key else r"(?:unidades?|units?)?")
            normalized = re.fullmatch(rf"(?P<n>{_NUM})\s*{expected_unit}", attr_value)
            add(attr_key, normalized["n"] if normalized else raw, source, f"{attr_key}: {raw}", raw)
            continue
        if source.startswith("attributes_json") and attr_key in {"abv", "pack_size"} and _number(attr_value) is not None:
            # ABV denotes percentage by definition. Family plausibility is checked
            # below, retaining the uncorrected raw value for manual review.
            field = "abv_pct" if attr_key == "abv" else "pack_count"
            add(field, attr_value, source, f"{attr_key}: {raw}", raw)
            continue
        if source.startswith("attributes_json") and attr_key == "pack_size" and re.fullmatch(r"x\s*\d{1,3}", attr_value):
            add("pack_count", re.search(r"\d+", attr_value).group(), source, f"pack_size: {raw}", raw)
            continue
        if source.startswith("attributes_json") and attr_key in {"sugar_free", "is_zero_alcohol"}:
            if attr_value == "true":
                facts.append(dict(field=attr_key + "_claim", value=True, source=source,
                                  evidence=f"{attr_key}: {raw}", raw_text=raw))
            elif attr_key == "is_zero_alcohol" and attr_value == "false":
                facts.append(dict(field="is_zero_alcohol_false_claim", value=False, source=source,
                                  evidence=f"{attr_key}: {raw}", raw_text=raw))
            continue
        if source.startswith("attributes_json"):
            text = f"{_fold(source.split('.')[-1]).replace('_', ' ')}: {text}"

        # Serving sizes are separate from sale/package volumes.
        for match in re.finditer(rf"\b(?:tamano de (?:la )?|size of )?{_SERVING}\s*(?:de|size|:|=|\()?\s*(?P<n>{_NUM})\s*(?P<u>{_UNIT})", text):
            add("serving_volume_ml", _ml(match["n"], match["u"]), source, match.group(), raw)
        for match in re.finditer(rf"(?P<n>{_NUM})\s*(?P<u>{_UNIT})\s*(?:por|per|/)\s*{_SERVING}\b", text):
            add("serving_volume_ml", _ml(match["n"], match["u"]), source, match.group(), raw)
        for match in re.finditer(rf"\b{_SERVING}\s*[:=]?\s*1\s*(?:botella|lata|vaso|bottle|can|cup)\s*\(\s*(?P<n>{_NUM})\s*(?P<u>{_UNIT})\s*\)", text):
            add("serving_volume_ml", _ml(match["n"], match["u"]), source, match.group(), raw)

        for match in _VOL.finditer(text):
            before, after = text[max(0, match.start() - 90):match.start()], text[match.end():match.end() + 35]
            nutrient_context = re.search(r"(?:azucar|sugar|carbohidrat|carbohydrat|proteina|grasas?|fat|sodio|sodium|energia|calorias)", before)
            basis_context = re.search(rf"(?:/|\bpor|\bper)\s*$|{_SERVING}\s*(?:de|size|:|=|\()?\s*$", before)
            after_basis = re.match(rf"\s*(?:por|per|/)\s*{_SERVING}\b|\s*[:=]\s*(?:azucar|sugar)", after)
            package = re.search(r"(?:contenido neto|net content|volumen|volume|presentacion|cada (?:botella|lata|unidad)|botella|lata|botellon)\s*[:=]?\s*$", before)
            if basis_context or after_basis or (nutrient_context and source != "name" and not package):
                continue
            if source not in {"name", "pack_format_raw"} and re.search(rf"{_SERVING}|nutricion|nutrition|nutricional", text[:match.start()]) and not package:
                continue
            if re.search(r"(?:contenido|volumen|volume)?\s*total\s*[:=]?\s*$", before) or re.match(r"\s*(?:en total|total)\b", after):
                field = "total_volume_ml"
            else:
                field = "volume_per_unit_ml"
            if re.fullmatch(r"\d{1,3}[.,]\d{3}", match["n"]):
                flags.add("ambiguous_volume_number_format")
                facts.append(dict(field="ambiguous_volume", value=match["n"], source=source,
                                  evidence=match.group(), raw_text=raw))
                continue
            add(field, _ml(match["n"], match["u"]), source, match.group(), raw)

        # Count and amount may be separated by a container word, but no arbitrary X-number.
        pack_patterns = [
            rf"\b(?P<n>\d{{1,3}})\s*[x×]\s*{_NUM}\s*{_UNIT}",
            rf"{_NUM}\s*{_UNIT}\s*[x×]\s*(?P<n>\d{{1,3}})\b",
            rf"\b(?:pack|paquete|multipack|caja|fardo)\s*(?:de|con|x)?\s*(?P<n>\d{{1,3}})(?![\d.,])(?!\s*{_UNIT})\b",
            r"\b(?P<n>\d{1,3})\s*(?:pack|unidades?|unds?|uds|latas?|botellas?|garrafas?)\b",
        ]
        for pattern in pack_patterns:
            for match in re.finditer(pattern, text):
                add("pack_count", match["n"], source, match.group(), raw)
        if source == "name":
            leading = re.match(r"\s*(?P<n>\d{1,3})\s*[x×]\s*(?=[a-z])", text)
            if leading:
                add("pack_count", leading["n"], source, leading.group(), raw)
        if re.search(r"\b(?:six\s*-?\s*pack|sixpack)\b", text):
            add("pack_count", 6, source, "six pack", raw)
        abv_patterns = [
            rf"\b(?:abv|alc(?:ohol)?(?:\s*(?:por volumen|by volume|vol))?|grado alcoholico|graduacion alcoholica|teor alcoolico)\s*[:=.]?\s*(?P<n>{_NUM})\s*%",
            rf"(?P<n>{_NUM})\s*%\s*(?:abv|alc(?:ohol)?|vol(?:\.|umen)?\b|v/v)",
            rf"(?P<n>{_NUM})\s*(?:°|grados?)\s*(?:g\.?\s*l\.?|alcoholicos?)\b",
        ]
        for pattern in abv_patterns:
            for match in re.finditer(pattern, text):
                if re.match(r"\s*(?:p/p|w/w|m/m|by weight|en peso)\b", text[match.end():]):
                    flags.add("alcohol_mass_fraction_not_abv")
                    continue
                if re.search(r"(?:[<>≤≥~]|menos de|mas de|less than|more than|hasta)\s*$", text[:match.start()]):
                    flags.add("abv_is_bound")
                    continue
                add("abv_pct", match["n"], source, match.group(), raw)

        # Sugar amounts must name sugar AND have an explicit denominator, or an
        # explicit serving basis. Do not match carbohydrates, percentages or DV.
        sugar_label = rf"(?:{_ADDED}\s+)?{_SUGAR}(?:\s+(?:totales?|total|{_ADDED}))?"
        sugar_patterns = [
            rf"(?P<label>{sugar_label})\s*[:=]?\s*(?P<n>{_NUM})\s*g\b",
            rf"(?P<n>{_NUM})\s*g\s*(?:de\s*)?(?P<label>{sugar_label})",
        ]
        for match in sorted((match for pattern in sugar_patterns for match in re.finditer(pattern, text)), key=lambda match: match.start()):
            tail = text[match.end():match.end() + 65]
            head = text[max(0, match.start() - 100):match.start()]
            value = float(match["n"].replace(",", "."))
            # A bound is evidence of a range, never the exact endpoint. This
            # matters especially for labels such as "menos de 1 g de azúcar".
            if re.search(r"(?:[<>≤≥~]|menos de|mas de|less than|more than|hasta|aprox(?:imadamente)?\.?)\s*$", head):
                flags.add("sugar_amount_is_bound")
                facts.append(dict(field="sugar_g_bound", value=value, source=source,
                                  evidence=head[-35:] + match.group(), raw_text=raw))
                continue
            if re.search(_ADDED, match["label"]):
                if value > 0:
                    facts.append(dict(field="added_sugar_positive", value=True, source=source, evidence=match.group(), raw_text=raw))
                # Added sugar is distinct from total sugar; don't silently fill it.
                flags.add("added_sugar_amount_not_total")
                continue
            denominator = re.match(rf"\s*(?:/|por|per|en|em)\s*(?P<n>{_NUM})\s*(?P<u>{_UNIT})", tail)
            prior_basis = list(re.finditer(rf"\b(?:por|per|en|em)\s*(?P<n>{_NUM})\s*(?P<u>{_UNIT})", head))
            prior_serving = list(re.finditer(rf"\b(?:por|per)\s*{_SERVING}\b", head))
            unsupported_basis = rf"(?:/|\bpor|\bper|\ben)\s*(?:{_NUM}\s*(?:kg|g|gr|gramos?)\b|(?:envase|botella|lata|paquete|container|bottle|package)\b)"
            prior_unsupported = list(re.finditer(unsupported_basis, head))
            last_supported = max([m.start() for m in [*prior_basis, *prior_serving]], default=-1)
            if re.match(rf"\s*{unsupported_basis}", tail) or (not denominator and prior_unsupported and prior_unsupported[-1].start() > last_supported):
                flags.add("sugar_amount_basis_unsupported")
                facts.append(dict(field="sugar_g_basis_unknown", value=value, source=source,
                                  evidence=match.group(), raw_text=raw))
                continue
            closest_is_serving = bool(prior_serving and (not prior_basis or prior_serving[-1].start() > prior_basis[-1].start()))
            basis = denominator or (prior_basis[-1] if prior_basis and not closest_is_serving else None)
            if basis:
                volume = _ml(basis["n"], basis["u"])
                if volume > 0:
                    add("sugar_g_per_100ml", round(value * 100 / volume, 8), source, match.group() + " | " + basis.group(), raw)
            elif re.match(rf"\s*(?:por|per|/)\s*{_SERVING}\b", tail) or closest_is_serving:
                add("sugar_g_per_serving", value, source, match.group(), raw)
            else:
                flags.add("sugar_amount_basis_unknown")
                facts.append(dict(field="sugar_g_basis_unknown", value=value, source=source, evidence=match.group(), raw_text=raw))
    # A singular title container is a fallback only: an explicit pack attribute
    # may specify several containers of the same product described in that title.
    if not any(fact["field"] == "pack_count" for fact in facts):
        raw_name = next((raw for source, raw in sources if source == "name"), "")
        name = _fold(raw_name)
        if re.search(r"\b(?:botella|lata|botellon|garrafa)\b", name) and not re.search(r"\b(?:pack|paquete|caja|sixpack|six|\d+\s*(?:unidades|botellas|latas))\b|[x×+]", name):
            add("pack_count", 1, "name", "singular container without contrary pack evidence", raw_name)
    return facts


def _classify(sources, facts, values, flags, country_code="", alcoholic_beverage=None,
              unit_type=""):
    name = _fold(next((text for source, text in sources if source == "name"), ""))
    # Classify the product title first; ingredients may contain e.g. water or alcohol.
    details = " ".join(_fold(text) for source, text in sources if source != "pack_format_raw")
    families = [family for family, pattern in _FAMILY.items() if re.search(pattern, name)]
    typed = {re.sub(r"^pps_", "", _fold(source.split(".")[-1])): text for source, text in sources
             if source.startswith("attributes_json.") and text.strip()
             and _fold(text.strip()) not in {"false", "none", "null", "nan", "n/a"}}
    typed_families = list(dict.fromkeys(_TYPED_FAMILY[key] for key in typed if key in _TYPED_FAMILY))
    if _fold(typed.get("category", "")) in {"bebidas de cereal", "bebidas lacteas"} and not typed_families:
        typed_families = ["other_beverage"]
    if families and families != ["other_beverage"] and typed_families:
        title_alcohol = any(f in _ALCOHOL for f in families)
        typed_alcohol = any(f in _ALCOHOL for f in typed_families)
        if title_alcohol != typed_alcohol or ("water" in families and any(f != "flavored_water" for f in typed_families)):
            if title_alcohol and values["abv_pct"] is not None and values["abv_pct"] > 0 and str(alcoholic_beverage).lower() == "true":
                flags.add("typed_non_alcohol_family_overridden_by_title_flag_and_positive_abv")
            else:
                flags.add("conflicting_typed_beverage_identity")
    if typed_families and (not families or families == ["other_beverage"]):
        # Conflicting typed alcohol/nonalcohol families establish only a generic
        # candidate identity. They do not justify assigning alcohol or plain water.
        if any(f in _ALCOHOL for f in typed_families) and any(f not in _ALCOHOL for f in typed_families):
            flags.add("conflicting_typed_beverage_identity")
            families = ["other_beverage"]
        else:
            families = typed_families
        flags.add("beverage_identity_from_typed_attributes")
    if not families and values["abv_pct"] is not None and values["abv_pct"] > 0:
        typed_wine = any("varietal_wine" in source or "wine_type" in source for source, text in sources if text.strip())
        typed_beer = any("beer_style" in source for source, text in sources if text.strip())
        if typed_wine or typed_beer:
            families = ["wine" if typed_wine else "beer"]
            flags.add("beverage_identity_from_typed_attributes")
        elif alcoholic_beverage is True or str(alcoholic_beverage).lower() == "true":
            families = ["cocktail"]
            flags.add("alcohol_identity_from_platform_flag_and_abv")
    water_flavor = any(key in {"flavor", "flavor_drinks", "flavor_beverage", "flavored_water_flavor"}
                      and _fold(value.strip()) not in {"original", "natural", "agua", "sin sabor", "unflavored", "otros"}
                      for key, value in typed.items())
    if "water" in families and (_WATER_MODIFIERS.search(name) or "flavored_water_flavor" in typed or water_flavor):
        families = ["flavored_water", *[family for family in families if family not in {"water", "flavored_water"}]]
    def permitted_context(match):
        token = match.group()
        if token in {"chocolate", "chocolates"}:
            drink_before = any(re.search(_FAMILY[f], name[:match.start()])
                               for f in ("dairy_beverage", "tea_coffee", "spirits"))
            prepared_chocolate = bool(re.search(r"\bchocolate (?:caliente|frio)\b", name))
            return (drink_before or prepared_chocolate) and not re.search(
                r"\b(?:tableta|alfajor|galleta|pan|torta|panqueque|bombon|barrita|helado)\b", name)
        if token == "helado":
            return bool(re.search(r"\b(?:te|cafe)\b.*\bhelado\b", name))
        if token == "vaso":
            return any(f in {"dairy_beverage", "tea_coffee", "juice", "other_beverage"} for f in families) and not re.search(
                r"\b(?:para|vidrio|plastico|acero|desechable|vacio)\b", name)
        if token == "concentrado":
            return bool(re.search(r"\bbebida\b.*\bcon\s+jugo\b.*\bconcentrado\b", name))
        return False

    exclusions = list(_EXCLUDE.finditer(name))
    exclusion = next((match for match in exclusions if not permitted_context(match)), None)
    chocolate_drink = any(match.group() in {"chocolate", "chocolates"} and permitted_context(match)
                          for match in exclusions)
    mass_only = bool(re.fullmatch(r"(?:g|gr|grs|kg|gramos?)", _fold(unit_type or "")) or re.search(r"\d\s*(?:kg|g|gr|gramos?)\b", name)) and values["volume_per_unit_ml"] is None
    food_identity = re.search(r"\b(?:carne|pollo|cerdo|camarones?|mariscos|lomo|bife|costillas?|bondiola|pescado)\b", name)
    alcohol_cooking = re.search(r"\b(?:al|a la|con)\s+(?:vino|cerveza|ron|whisky|vodka)\b", name)
    if food_identity and (mass_only or alcohol_cooking):
        return "excluded", "prepared_food", "food identity; alcohol is a preparation ingredient", "unknown"
    fruit_cocktail = bool(re.search(r"\b(?:coctel|cocktail)\s+(?:de\s+)?frutas?\b", name))
    if fruit_cocktail and mass_only:
        return "excluded", "fruit_preparation", "mass-denominated fruit cocktail food", "unknown"
    if fruit_cocktail and not (values["abv_pct"] is not None and values["abv_pct"] > 0):
        return "review", "fruit_cocktail", "fruit cocktail does not establish an alcoholic beverage", "unknown"
    if "powdered_beverages_flavor" in typed or "cocktail_bases" in typed:
        return "excluded", "out_of_scope", "typed powder or cocktail-base attribute; not ready to drink", "unknown"
    sweetener_title = re.search(r"\b(?:edulcorante|endulzante|azucar)\b", name)
    if (sweetener_title and any(key in typed for key in ("sweetener_type", "sugar_type"))
            and not any(re.search(pattern, name[:sweetener_title.start()]) for pattern in _FAMILY.values())):
        return "excluded", "table_sweetener", "typed tabletop sweetener identity; not a ready-to-drink beverage", "unknown"
    if chocolate_drink and any(key in typed for key in ("chocolate_type", "chocolate_filling", "candy_type")):
        flags.add("conflicting_beverage_food_identity")
        return "review", families[0], "beverage title conflicts with typed confectionery attributes", "unknown"
    if exclusion:
        return "excluded", "out_of_scope", "non-beverage or non-ready-to-drink title", "unknown"
    if "tea_coffee" in families and mass_only and "ready_tea_flavor" not in typed:
        return "excluded", "dry_tea_coffee", "mass-only tea/coffee listing lacks ready-to-drink evidence", "unknown"
    if mass_only:
        flags.add("mass_only_sale_unit")
        return "review", families[0] if families else "unknown", "sale unit is mass; ready-to-drink identity needs review", "unknown"
    # A juice cocktail is a juice product label; "cocktail" alone must not turn
    # it into alcohol. Explicit alcohol/ABV evidence keeps the conflict in review.
    juice_cocktail = "cocktail" in families and ("juice" in families or "flavor_juices" in typed)
    if juice_cocktail and not any(f in {"spirits", "wine", "beer"} for f in families):
        families = ["juice", *[f for f in families if f not in {"juice", "cocktail"}]]
        flags.add("juice_cocktail_not_alcohol_identity")
    alcohol_title = any(family in _ALCOHOL for family in families)
    sugar_claims = list(_NO_SUGAR.finditer(details))
    # Beer "Zero" commonly identifies an alcohol-free variant. A generic Zero or
    # Diet label on an alcohol family is not a sugar-specific statement.
    no_sugar = any(not alcohol_title or match.group() not in {"zero", "diet", "dietetica", "dietetico"} for match in sugar_claims) or any(fact["field"] == "sugar_free_claim" for fact in facts) or values["sugar_g_per_100ml"] == 0
    no_added_sugar = bool(_NO_ADDED_SUGAR.search(details))
    unsweetened = bool(_UNSWEETENED.search(details))
    sweetened = bool(_SWEETENED.search(details)) or any(fact["field"] == "added_sugar_positive" for fact in facts)
    # Ingredient evidence names an actual caloric sweetener, not generic nutrition.
    ingredients = re.search(r"\b(?:ingredientes?|ingredients?)\s*[:=]([^\n.;]+)", details)
    if ingredients and re.search(r"\b(?:azucar|acucar|sugar|panela|jarabe de (?:maiz|glucosa|fructosa)|sirope|miel|honey)\b", ingredients[1]):
        sweetened = True
    status = "sugar_sweetened" if sweetened else "unsweetened" if unsweetened else "no_sugar_claim" if no_sugar else "no_added_sugar_claim" if no_added_sugar else "unknown"
    conflict = sweetened and (no_sugar or no_added_sugar or unsweetened)
    if conflict:
        status = "unknown"
        flags.add("conflicting_sugar_claims")
    subcategory = families[0] if families else "unknown"
    if "flavored_water" in families and subcategory in {"water", "other_beverage"}:
        subcategory = "flavored_water"
    if "conflicting_typed_beverage_identity" in flags:
        return "review", subcategory, "typed beverage family conflicts with title or another typed family", status
    alcohol = any(family in _ALCOHOL for family in families)
    nonalcohol = bool(_NON_ALCOHOL.search(name)) or (alcohol and bool(re.search(r"\b0[.,]0\b", name))) or ("beer" in families and bool(re.search(r"\bzero\b", name))) or any(fact["field"] == "is_zero_alcohol_claim" for fact in facts)
    if "beer" in families and re.search(r"\bginger beer\b", name) and not nonalcohol and not (values["abv_pct"] is not None and values["abv_pct"] > 0):
        flags.add("ginger_beer_alcohol_status_unknown")
        return "review", "ginger_beer_mixer", "ginger beer/mixer name does not establish alcohol content", status
    if alcohol:
        if "zero_abv_conflicts_with_alcohol_flag" in flags:
            return "review", subcategory, "zero ABV contradicts explicit platform alcohol status", status
        if values["abv_pct"] == 0 and not nonalcohol:
            flags.add("zero_abv_without_nonalcoholic_identity")
            return "review", subcategory, "zero ABV conflicts with alcoholic identity without a nonalcoholic claim", status
        if nonalcohol:
            flags.add("nonalcoholic_variant")
            if values["abv_pct"] is not None and values["abv_pct"] > 0:
                flags.add("nonalcoholic_claim_with_positive_abv")
                return "review", subcategory, "nonalcoholic claim with positive stated ABV", status
            if conflict:
                return "review", subcategory, "conflicting sugar claims", status
            if sweetened:
                return "ssb", subcategory, "nonalcoholic variant with explicit sweetening", status
            return "non_ssb" if no_sugar or no_added_sugar or unsweetened else "review", subcategory, "nonalcoholic variant; sugar status needs evidence", status
        return "alcohol", subcategory, "explicit alcoholic beverage type", status
    if not families:
        if values["abv_pct"] is not None and values["abv_pct"] > 0:
            return "review", "unknown", "ABV without a recognized beverage identity", status
        return "review", "unknown", "no specific beverage identity in title", status
    if conflict:
        return "review", subcategory, "conflicting sugar claims", status
    if values["abv_pct"] is not None and values["abv_pct"] > 0:
        flags.add("positive_abv_non_alcohol_title")
        return "review", subcategory, "positive ABV needs beverage-type review", status
    if sweetened:
        return "ssb", subcategory, "explicit caloric sweetener evidence", status
    plain_soda = bool(re.search(r"\bsoda\b", name)) and not re.search(r"\b(?:sabor|tonica|probio|lima|limon|pomelo|naranja|durazno|jengibre|melon|peach|cream|fruta|vainilla|cola|cereza|fresa|frutilla)", details)
    if plain_soda and (str(country_code).lower() == "ar" or re.search(r"\bsifon\b|\bpura agua\b", name)):
        return "water", "sparkling_water", "plain soda/siphon water identity in local context", status
    if subcategory == "water" and "flavored_water" not in families:
        return "water", "sparkling_water" if re.search(r"\b(?:con gas|gasificada|mineral con gas|sparkling|seltzer)\b", name) else "plain_water", "plain drinking-water identity", status
    if no_added_sugar and not (no_sugar or unsweetened):
        return "non_ssb", subcategory, "explicit no-added-sugar claim; total sugar may still be present", status
    if no_sugar or unsweetened:
        return "non_ssb", subcategory, "explicit no-sugar/unsweetened claim; retained comparison", status
    return "review", subcategory, "beverage candidate; added-sugar status unconfirmed", status


def _has_explicit_per_unit_basis(facts: list[dict]) -> bool:
    """A volume fact must state its unit basis when any multipack is possible."""
    for fact in facts:
        if fact["field"] != "volume_per_unit_ml":
            continue
        key = _fold(fact["source"].rsplit(".", 1)[-1]).replace(" ", "_")
        if key == "volume_per_unit_ml":
            return True
        text = _fold(fact["raw_text"])
        explicit_pair = re.search(rf"\b\d+\s*[x×]\s*{_NUM}\s*{_UNIT}|{_NUM}\s*{_UNIT}\s*[x×]\s*\d+\b", text)
        explicit_container = re.search(rf"\b(?:latas?|botellas?|unidades?|garrafas?|bottles?|cans?|units?)\s*(?:de|of|:)?\s*{_NUM}\s*{_UNIT}", text)
        explicit_each = re.search(r"\b(?:cada uno|cada una|cada (?:botella|lata|unidad)|por unidad|per (?:unit|bottle|can)|each)\b", text)
        if explicit_pair or explicit_container or explicit_each:
            return True
    return False


def _enrich_single(row: dict) -> dict:
    """Return auditable beverage fields without modifying the source observation."""
    flags: set[str] = set()
    sources = _sources(row)
    facts = _extract_facts(sources, row, flags)
    output: dict[str, Any] = {}
    for field in _FIELDS:
        matches = [fact for fact in facts if fact["field"] == field]
        values = {fact["value"] for fact in matches}
        output[field] = next(iter(values)) if len(values) == 1 else None
        output[field + "_source"] = "|".join(dict.fromkeys(fact["source"] for fact in matches)) or None
        output[field + "_evidence"] = " | ".join(dict.fromkeys(fact["evidence"] for fact in matches)) or None
        if len(values) > 1:
            flags.add("conflicting_" + field)

    name = _fold(row.get("name") or "")
    # A leading integer without a multiplier is ambiguous (it can be a count or
    # part of a brand). It must not silently inherit one bottle from presentation.
    explicit_count_noun = re.match(r"^\s*\d+\s+(?:pack|paquete|botellas?|unidades?|latas?|garrafas?)\b", name)
    # Observed numeric brand prefixes are product identities, not quantities.
    # Every other leading count is kept ambiguous across all drink families.
    numeric_brand = re.match(r"^(?:7\s+up|3\s+cordilleras|5\s+flores|7\s+vidas|7\s+colores|14\s+inkas|4\s+gallos)\b", name)
    explicit_title_multiplier = re.match(r"^\s*\d+\s*[x×]\s*", name)
    leading_count = re.match(r"^\s*(?P<n>[2-9]|[1-9]\d)\s+[a-z]", name)
    corroborated_count = bool(leading_count and output["pack_count"] == int(leading_count["n"]))
    if leading_count and not (explicit_count_noun or numeric_brand or explicit_title_multiplier or corroborated_count):
        flags.add("ambiguous_title_count")
        output["pack_count"] = None
    # "X6", "duopack", and a bare "pack" can contradict the platform's
    # single-sale-unit presentation without enough evidence to resolve a count.
    title_multipliers = [int(match["n"]) for match in re.finditer(
        rf"(?<!\w)[x×]\s*(?P<n>\d{{1,3}})(?![\d.,])(?!\s*(?:{_UNIT}|g\b|kg\b|anos?\b))\b", name)]
    title_multipack = re.search(r"\b(?:pack|multipack|six|sixpack|duopack|duo\s+pack|bipack|tripack|tri\s+pack|twelve(?:pack)?)\b|\b(?:duo|trio)\s+cervezas?\b", name)
    name_count = any(fact["field"] == "pack_count" and fact["source"] == "name" for fact in facts)
    if ((title_multipliers and any(n != output["pack_count"] for n in title_multipliers)) or
            (title_multipack and not name_count and output["pack_count"] in (None, 1))):
        flags.add("ambiguous_title_multipack")
        output["pack_count"] = None
    # A concatenated suffix such as "6x300mLTapa" is deliberately not repaired:
    # it still contradicts a 1×300mL presentation and invalidates its denominator.
    if re.search(r"\b\d+\s*[x×]\s*\d+(?:[.,]\d+)?\s*(?:ml|cl|cc|lt|l)(?=[a-z])", name):
        flags.add("malformed_title_pack_unit")
        output["pack_count"] = None
    promotional_count = any(int(match["buy"]) > int(match["pay"]) for match in re.finditer(
        rf"\b(?P<buy>\d{{1,2}})\s*[x×]\s*(?P<pay>\d{{1,2}})(?![\d.,])(?!\s*{_UNIT})\b", name))
    if promotional_count:
        flags.add("promotional_quantity_ambiguous")
        output["pack_count"] = None
    if output["abv_pct"] == 0 and any(fact["field"] == "is_zero_alcohol_false_claim" for fact in facts):
        flags.add("conflicting_abv_pct")
        flags.add("zero_abv_conflicts_with_alcohol_flag")
        output["abv_pct"] = None
    if "ambiguous_volume_number_format" in flags:
        output["volume_per_unit_ml"] = output["total_volume_ml"] = None
    mixed = bool(re.search(r"\b(?:combo|surtido|surtida|mix|mixto|mixta|kit)\b|\s\+\s|\d\s*(?:ml|l)\s*\+", name))
    if mixed:
        flags.add("mixed_or_ambiguous_bundle")
        for field in _FIELDS:
            output[field] = None
    possible_multipack = (bool(title_multipack) or
        any(fact["field"] == "pack_count" and fact["value"] > 1 for fact in facts) or
        bool(flags.intersection({"ambiguous_title_count", "ambiguous_title_multipack",
                                 "malformed_title_pack_unit", "promotional_quantity_ambiguous"})))
    if not mixed and possible_multipack and output["volume_per_unit_ml"] is not None:
        if not _has_explicit_per_unit_basis(facts):
            flags.add("ambiguous_pack_volume_basis")
            output["volume_per_unit_ml"] = None
            # Before derivation, an existing total is independent explicit
            # evidence. Unknown container count must not erase that sale volume.
    if not mixed:
        per_unit, count, total = (output[key] for key in ("volume_per_unit_ml", "pack_count", "total_volume_ml"))
        if per_unit is not None and count is not None:
            calculated = round(per_unit * count, 6)
            if total is not None and abs(total - calculated) > 0.01:
                flags.add("conflicting_total_volume_ml")
                output["total_volume_ml"] = None
            elif "conflicting_total_volume_ml" not in flags:
                output["total_volume_ml"] = calculated
                output["total_volume_ml_source"] = output["total_volume_ml_source"] or "derived:volume_per_unit_ml*pack_count"
                output["total_volume_ml_evidence"] = output["total_volume_ml_evidence"] or f"{per_unit} mL * {count} units"
        serving, sugar = output["serving_volume_ml"], output["sugar_g_per_serving"]
        if serving is not None and sugar is not None and "conflicting_sugar_g_per_100ml" not in flags:
            calculated = round(sugar * 100 / serving, 8)
            if calculated > 100:
                flags.add("invalid_sugar_g_per_100ml")
                output["sugar_g_per_100ml"] = None
            elif output["sugar_g_per_100ml"] is None:
                output["sugar_g_per_100ml"] = calculated
                output["sugar_g_per_100ml_source"] = "derived:sugar_g_per_serving/serving_volume_ml*100"
                output["sugar_g_per_100ml_evidence"] = f"{sugar} g / {serving} mL * 100"
            elif abs(output["sugar_g_per_100ml"] - calculated) > 0.1:
                flags.add("conflicting_sugar_g_per_100ml")
                output["sugar_g_per_100ml"] = None
    category, subcategory, reason, status = _classify(sources, facts, output, flags,
                                                  row.get("country_code", ""), row.get("alcoholic_beverage"), row.get("unit_type"))
    # These are review thresholds, not universal limits on possible products.
    # In particular a raw beer attribute "50" must never be silently divided by ten.
    review_abv_limit = {"beer": 20, "wine": 25}.get(subcategory)
    if review_abv_limit is not None and output["abv_pct"] is not None and output["abv_pct"] > review_abv_limit:
        flags.add("unusual_abv_requires_review")
        output["abv_pct"] = None
        category, reason = "review", "stated ABV exceeds beverage-family review threshold"
    volume = output["volume_per_unit_ml"]
    if category != "excluded" and volume is not None and (volume < 30 or volume > 30000):
        flags.add("unusual_volume_requires_review")
        output["volume_per_unit_ml"] = output["total_volume_ml"] = None
        category, reason = "review", "stated package volume outside first-pass review range"
    bundle_has_beverage = any(re.search(pattern, name) for pattern in _FAMILY.values())
    if mixed and (category != "excluded" or bundle_has_beverage):
        category, reason = "review", "mixed/ambiguous bundle requires component-level review"
    output.update(beverage_category=category, beverage_subcategory=subcategory,
                  classification_reason=reason, sugar_status=status)
    if category != "excluded":
        if output["volume_per_unit_ml"] is None:
            flags.add("volume_unknown")
        if output["pack_count"] is None:
            flags.add("pack_count_unknown")
        if category in {"ssb", "review"} and output["sugar_g_per_100ml"] is None:
            flags.add("sugar_concentration_unknown")
        if category == "alcohol" and output["abv_pct"] is None:
            flags.add("abv_unknown")
    output["beverage_flags"] = sorted(flags)
    output["beverage_evidence_json"] = json.dumps(facts, ensure_ascii=False, sort_keys=True)
    return output


def enrich_beverage(row: dict) -> dict:
    """Enrich one observation and quarantine composition conflicts across queries."""
    output = _enrich_single(row)
    conflicts = row.get("source_conflicts_json") or []
    if isinstance(conflicts, str):
        try:
            conflicts = json.loads(conflicts)
        except ValueError:
            output["beverage_flags"] = sorted(set(output["beverage_flags"]) | {"invalid_source_conflicts_json"})
            return output
    if not isinstance(conflicts, list) or not conflicts:
        return output
    flags = set(output["beverage_flags"]) | {"source_conflict"}
    evidence = json.loads(output["beverage_evidence_json"])
    numeric_conflicts = set()
    composition_conflict = False
    relevant = {"name", "short_description", "attributes_json", "quantity", "unit_type", "pack_format_raw", "presentation"}
    # An explicit uncertainty in another sighting is different from an omitted
    # field. The single-row parser can reject it before producing numeric facts,
    # so comparing only nonblank values would leave the first value trusted.
    uncertainty_fields = {
        "ambiguous_title_count": {"pack_count"},
        "ambiguous_title_multipack": {"pack_count"},
        "malformed_title_pack_unit": {"pack_count"},
        "promotional_quantity_ambiguous": {"pack_count"},
        "ambiguous_pack_volume_basis": {"volume_per_unit_ml"},
        "ambiguous_volume_number_format": {"volume_per_unit_ml", "total_volume_ml"},
        "unusual_volume_requires_review": {"volume_per_unit_ml", "total_volume_ml"},
        "unusual_abv_requires_review": {"abv_pct"},
        "abv_is_bound": {"abv_pct"},
        "alcohol_mass_fraction_not_abv": {"abv_pct"},
        "sugar_amount_is_bound": {"sugar_g_per_100ml", "sugar_g_per_serving"},
        "sugar_amount_basis_unsupported": {"sugar_g_per_100ml", "sugar_g_per_serving"},
        "sugar_amount_basis_unknown": {"sugar_g_per_100ml", "sugar_g_per_serving"},
        "mixed_or_ambiguous_bundle": set(_FIELDS),
    }
    uncertainty_fields.update({f"invalid_{field}": {field} for field in _FIELDS})
    for index, conflict in enumerate(conflicts):
        if not isinstance(conflict, dict):
            continue
        changes = conflict.get("fields") or {}
        if not isinstance(changes, dict) or not relevant.intersection(changes):
            continue
        later = dict(row)
        for key, change in changes.items():
            if isinstance(change, dict) and "later" in change:
                later[key] = change["later"]
                if key == "presentation":
                    later["pack_format_raw"] = change["later"]
        alternate = _enrich_single(later)
        alternate_evidence = json.loads(alternate["beverage_evidence_json"])
        uncertain = set()
        for flag in alternate["beverage_flags"]:
            affected = uncertainty_fields.get(flag, set())
            # Keep a valid first observation when a later response simply omits
            # nutrition/package text. Only explicit invalidity or ambiguity
            # invalidates the earlier numeric value here.
            invalidated = {field for field in affected if output[field] is not None}
            if invalidated:
                uncertain.update(invalidated)
                flags.add("cross_query_" + flag)
        # A later outlier can already be blanked by the single-row checks; compare
        # its explicit facts too so the first nonblank value is not left trusted.
        raw_conflicts = set()
        for field in _FIELDS:
            first_values = {fact["value"] for fact in evidence if fact["field"] == field and not fact["source"].startswith("duplicate_query")}
            later_values = {fact["value"] for fact in alternate_evidence if fact["field"] == field}
            if first_values and later_values and first_values != later_values:
                raw_conflicts.add(field)
        changed_numeric = {field for field in _FIELDS if (
            output[field] is not None and alternate[field] is not None and output[field] != alternate[field]) or
            (f"conflicting_{field}" in alternate["beverage_flags"] and f"conflicting_{field}" not in output["beverage_flags"])} | raw_conflicts | uncertain
        changed_classification = any(output[key] != alternate[key] for key in ("beverage_category", "beverage_subcategory", "sugar_status"))
        if changed_numeric or changed_classification:
            composition_conflict = True
            numeric_conflicts.update(changed_numeric)
            for fact in json.loads(alternate["beverage_evidence_json"]):
                evidence.append({**fact, "source": f"duplicate_query[{index}].{fact['source']}",
                                 "query": conflict.get("query"), "raw_file": conflict.get("raw_file")})
    if composition_conflict:
        flags.add("cross_query_composition_conflict")
        if (numeric_conflicts.intersection({"volume_per_unit_ml", "pack_count"}) and
                not any(fact["field"] == "total_volume_ml" and
                        not fact["source"].startswith("duplicate_query") for fact in evidence)):
            numeric_conflicts.add("total_volume_ml")
        if (numeric_conflicts.intersection({"sugar_g_per_serving", "serving_volume_ml"}) and
                not any(fact["field"] == "sugar_g_per_100ml" and
                        not fact["source"].startswith("duplicate_query") for fact in evidence)):
            numeric_conflicts.add("sugar_g_per_100ml")
        for field in numeric_conflicts:
            output[field] = None
            flags.add("cross_query_conflicting_" + field)
        output["beverage_category"] = "review"
        output["classification_reason"] = "composition or beverage identity differs across query sightings"
    output["beverage_flags"] = sorted(flags)
    output["beverage_evidence_json"] = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    return output
