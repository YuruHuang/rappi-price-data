"""Stage C — deterministic post-rules for the CO tobacco pipeline.

light by design: Stage A already encodes the FP/FN logic. Stage C only enforces
a couple of invariants on the merged row dict (after Stage A):

  * paraphernalia / candy stay out_of_scope (hard floor — an ashtray can't be re-promoted);
  * has_antismoking + a tobacco term in the NAME and a non-tobacco label ->
    promote to tobacco (defensive net for FN);
  * a catalog row shelved in the store's OWN tobacco aisle -> tobacco (the catalog's menu_section is
    the real aisle, unlike search's category bucket), accessories excluded;
  * flags is always a list.
"""
from __future__ import annotations

import json
import re

from rappi_co.classify.tobacco_classifier import (
    _first_hit, _normalize, _truthy, load_lexicon,
)

# NOTE: names below are matched against _normalize()d text (lowercased, accents stripped, and
# &/-/_/ etc. collapsed to spaces), so patterns must use spaces, not '&'/'-'/'\bml\b' boundaries.

# Accessory aisles (rolling papers, lighters, "otros accesorios") are not product aisles.
_ACCESSORY_SECTION_RE = re.compile(r"accesorio|papel|encendedor")
# Accessory / paraphernalia / hardware product names that stay out even when shelved in a tobacco
# aisle (head shops mix pipes, grinders and dab tools into the vape aisle). 'filtro' is intentionally
# NOT here: "con filtro" is a common cigarette descriptor.
_ACCESSORY_NAME_RE = re.compile(
    r"encendedor|bateria|cargador|resistencia|\bcoil|\bmalla|estuche|funda|cenicero|grinder|"
    r"triturador|trillador|moledor|molino|boquilla|charol|bandeja|\bcable|adaptador|repuesto|"
    r"\bpapers?\b|hemp paper|rolling paper|\bocb\b|\braw\b|hemp wrap|blunt wrap|herbal wrap|\bwraps?\b|"
    r"base cargadora|pyrex|tanque|atomizador vacio|pod vacio|organizador|balanza|pesa|limpiador|"
    r"limpia ?pipa|destornillador|\bpipa\b|\bpipas\b|\bpala\b|extraccion|\bbong|chillum|tacador|"
    r"\bcono\b|\bconos\b|rascador|\bdab|\bpitillo|\bpipe\b|smoking pipe|glass pipe|hierba seca|"
    r"dry herb|one.?hitter|despuntador|"
    r"cortapuro|corta puro|guillotina|area 420|fuego y papel|combo esencial|nectar collector|"
    r"water ?pipe|gotero|jeringa|banger|\brig\b|percolador|humidificador de puros|humidor")

# Universal demote: non-nicotine items Stage A over-promotes to tobacco via keyword_strong /
# keyword_context (which have NO accessory guard). Applied to EVERY tobacco row regardless of method:
#   * empty rolling material -- blunts, wraps (incl. tobacco-free hemp/herbal wraps), rolling papers,
#     "cueros"/leaf sheets (paraphernalia, not a finished smoke);
#   * bare vape/e-cig hardware -- batteries, mods, chargers, coils, resistances, empty pods/atomizers;
#   * cigarette rolling / filling machines;
#   * unambiguous smoking devices -- grinders, bongs, chillums.
# NOTE: a nicotine-FREE *vape* (e.g. "sin nicotina 0 mg") stays in scope -- sin-tax covers the vaping
# device regardless of nicotine content -- so tobacco-free wording alone is NOT a demote signal; only
# the rolling-material / hardware nature is. Deliberately excludes '\bpipa\b' (see _PIPE_DEVICE_RE) so
# real pipe TOBACCO is not swept up.
_NONTOBACCO_DEMOTE_RE = re.compile(
    r"\bblunt|\bwraps?\b|hemp wrap|herbal wrap|\bpapel|\bcueros?\b|rolling paper|"
    r"\bbateria\b|\bmod\b|\bcargador\b|\bresistencia\b|\bcoil\b|\bmalla\b|"
    r"atomizador vacio|pod vacio|base cargadora|"
    r"maquina .{0,8}(armar|llenar|enrollar)|rolling machine|\benrollador|"
    r"grinder|triturador|moledor|\bbong|chillum|nectar collector|"
    # filter TIPS ("Filtros ...", "Mini Filtros para cigarrillo 6mm") are accessories, but keep the
    # cigarette descriptors "con filtro" / "sin filtro"; the lookbehinds exclude only those two forms.
    r"(?<!con )(?<!sin )\bfiltros?\b")
_STUDY_NONTOBACCO_DEMOTE_RE = re.compile(
    r"\bconos?\b|\bcannabis\b|\bthc\b|\bcbd\b|"
    r"cuchara de tabaco|tabaquera|"
    r"estuche (?:para |de )?(?:tabaco|cigarr|vape)|porta ?tabaco|\bbattery\b|"
    r"cortador de cigarros?|autobronceador|\bself tan\b|\bruntz\b|liquid diamond|"
    r"dozo torch|half bakd|packman switch|escobars.*\bindic|mag elf th|fume delta 8|"
    r"insecticid|plaguicid|contra mosquitos?|mata al mosquito|"
    r"\bvibrad|\bvibrating\b|\bpower panty\b|\bbala huevo bang\b|\bbang grooved\b|"
    r"\baclarador\b|^bebida drink zyn\b|"
    r"^gift box\b|^box\b.*(?:san valentin|cafeter|cheler|cookie|feliz|para ellos|gift)|"
    r"astrologia.*\bbox\b|"
    r"\bcombo\b.*(?:cerveza|caguamita|monster energizante|hielo club)|"
    r"voopoo.*(?:pnp vm|tpp dm|tanque)|ohms?\b|"
    r"\byocan\b|vaporizador de (?:ceras?|hierba)|"
    r"\blookah\b.*\bunicorn\b|\bunicorn\b.*\blookah\b|"
    r"\bcigarro device\b|\bstlth loop (?:\d+ )?device\b|"
    r"\bvape waka creator (?:device|dispositivo)\b|\brelx (?:vape )?essential\b|"
    r"\bstlth loop (?:\d+ )?bateria\b|\bstlth loop bateria \d+\b")
_STUDY_KIT_COLLISION_RE = re.compile(
    r"\bruntz\b|liquid diamond|dozo torch|half bakd|packman switch|"
    r"escobars.*\bindic|"
    r"mag elf th|fume delta 8|insecticid|plaguicid|mosquito|\bvibrad|\bvibrating\b|"
    r"\bpower panty\b|\bbala huevo bang\b|\bbang grooved\b|\baclarador\b|"
    r"^bebida drink zyn\b|^gift box\b|^box\b.*(?:san valentin|cafeter|cheler|cookie|"
    r"feliz|para ellos|gift)|astrologia.*\bbox\b|"
    r"\bcombo\b.*(?:cerveza|caguamita|monster energizante|hielo club)|"
    r"voopoo.*(?:pnp vm|tpp dm|tanque)|ohms?\b|"
    r"\byocan\b|vaporizador de (?:ceras?|hierba)|"
    r"\blookah\b.*\bunicorn\b|\bunicorn\b.*\blookah\b|"
    r"\bstlth loop (?:\d+ )?bateria\b|\bstlth loop bateria \d+\b")

# Finished products are sometimes filed under a store's generic accessories aisle. A descriptor in
# the product name lets those rows survive the aisle guard; explicit hardware/paraphernalia terms
# above still take precedence.
_FINISHED_PRODUCT_RE = re.compile(
    r"puff|\bpufs?\b|aspiraciones?|\d\s?mg\b|\d\s?%|\bpod|boxpod|\bvape|vaper|vapead|"
    r"cigarrill|cajetill|nicotin|"
    r"\bpouch|desechable|disposable|\be ?liquids?\b|\d\s?ml\b|heets|terea|iluma|"
    r"extre bar|\d+\s?k\b")
_KIT_EXCLUSION_RE = re.compile(
    r"\bblunt|\bwraps?\b|\bpapel|\bcueros?\b|rolling paper|atomizador vacio|pod vacio|"
    r"maquina .{0,8}(armar|llenar|enrollar)|rolling machine|\benrollador|grinder|triturador|"
    r"moledor|\bbong|chillum|nectar collector|\bconos?\b|"
    r"\bcannabis\b|\bthc\b|"
    r"\bcbd\b|cuchara de tabaco|tabaquera|estuche|porta ?tabaco|(?<!con )(?<!sin )\bfiltros?\b")

_EXPLICIT_VAPE_CAPACITY_RE = re.compile(
    r"\d[\d .]*\s*(?:k\s*)?(?:puffs?|pufs?|aspiraciones?|caladas?)\b")
_KNOWN_VAPE_MODEL_RE = re.compile(
    r"\b(?:dojo|nexa|dragbar|sea bear|spaceman|hqd|geek ?bar|lost mary|smok|elf ?bar|"
    r"extre bar|fume|mijo|stlth|life pod|glucloud|oxbar|waka|relx|lophty|vuse)\b.*"
    r"(?:\d{1,3}\s*k\b|[a-z]{0,4}\d{4,6}\b|"
    r"\d{1,3}[., ]\d{3}\b)")
_KNOWN_VAPE_BRAND_RE = re.compile(
    r"\b(?:dojo|nexa|dragbar|sea bear|spaceman|hqd|geek ?bar|lost mary|smok|elf ?bar|"
    r"extre bar|fume|mijo|stlth|life pod|glucloud|oxbar|waka|relx|lophty|vuse)\b")
_VAPE_MODEL_CAPACITY_RE = re.compile(
    r"\b(?:\d{1,3}\s*k|[a-z]{0,4}\d{4,6}|\d{1,3}[., ]\d{3})\b")
_HARD_VAPE_COMPONENT_RE = re.compile(
    r"\b(?:coil|resistencia|malla|cargador|charger|tanque|tank)\b|"
    r"ohms?\b|atomizador vacio|pod vacio")
_VAPE_SYSTEM_RE = re.compile(
    r"\b(?:pod|cartucho|refill|dispositivo|vape desechable|vape disposable)\b")
_EXPLICIT_NON_VAPE_TOBACCO_RE = re.compile(
    r"\bpouches?\b|bolsas? de nicotina|\bsnus\b|\bterea\b|\bheets\b|\biqos\b|\biluma\b")
_VAPE_IDENTITY_RE = re.compile(
    r"\b(?:vape|vapes|vaper|vapers|vapeador|vapeadores|boxpod|e ?liquids?|liquido|"
    r"pod|pods|refill|cartucho|desechable|disposable)\b")
_STUDY_V2_LIQUID_RE = re.compile(
    r"^v2 liquido\b.*\d+(?:[.,]\d+)?\s*x\s*10\s*ml\b")
_HEATED_WELCOME_KIT_RE = re.compile(r"\b(?:kit|combo)(?: de)? bienvenida\b")
_HEATED_DEFINITIVE_CONSUMABLE_RE = re.compile(
    r"\b(?:terea|heets|cajetillas?|carton|heatsticks?)\b|"
    r"\b(?:tabaco|tobacco|heated) sticks?\b")
_HEATED_BARE_STICK_RE = re.compile(r"\bsticks?\b")
_HEATED_MODEL_RE = re.compile(
    r"^(?:(?:combo|oferta|nuevo|nueva)\s+)*"
    r"(?:iqos$|iqos\s+(?:iluma|originals?|(?:3\s+)?duo|multi|one|prime)\b|iluma\b)")

# ---- Study-only semantic product boundaries (generalized, not title literals) ----------------
# 1) Heated-tobacco hardware: an IQOS/ILUMA title that names the device/body (or is a bare IQOS
#    model title) and proves no consumable (TEREA/HEETS/sticks/cajetilla/carton) and is not an
#    explicitly titled welcome kit.
_HEATED_BRAND_RE = re.compile(r"\b(?:iqos|iluma)\b")
_HEATED_DEVICE_TERM_RE = re.compile(
    r"\b(?:dispositivo|dispositivos|device|devices|body|cuerpo|holder|kit|kits)\b")
_HEATED_ENGLISH_ACCESSORY_RE = re.compile(
    r"\b(?:case|cases|charger|chargers|charging case|cover|covers|sleeve|sleeves)\b")
_HEATED_CASE_OF_PACKS_RE = re.compile(
    r"\bcase of \d+\b.*\b(?:terea|heets)\b.*\bpacks?\b")
# 2) Edible collision: gummy noun + mg dose (or a title that *is* a gummy product) with no
#    independent vape identity. Gummy-flavour vapes keep their vape/puff/pod/brand evidence.
_GUMMY_TOKEN_RE = re.compile(r"\b(?:goma|gomas|gomita|gomitas|gummy|gummies|gummys)\b")
_GOMA_MAGICA_RE = re.compile(r"\b(?:goma|gomas|gomita|gomitas) magicas?\b")
_MG_DOSE_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*mg\b")
_EXPLICIT_VAPE_IDENTITY_RE = re.compile(
    r"\b(?:vape|vapes|vaper|vapers|vapeador|vapeadores|boxpod|e ?liquids?|pods?|"
    r"refill|cartucho)\b")
_GENERIC_VAPE_LIQUID_RE = re.compile(r"\b(?:liquido|liquid)\b")
_VOLUME_ML_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*ml\b")
_SAFE_VAPE_MODEL_CAPACITY_RE = re.compile(
    r"\b(?:\d{1,3}\s*k|[a-z]{0,4}\d{4,6}|\d{1,3}[., ]\d{3})\b(?!\s*mg\b)")
# 3) Homeware collision on a context-required brand (Camel/Master/Kent/Box...): dishware and
#    and home-goods nouns, plus only explicit product language that can rescue a genuine bundle.
#    Style/pack words such as box, XL, light and bare counts are deliberately not evidence.
_STUDY_HOMEWARE_NOUN_RE = re.compile(
    r"\b(?:bowls?|platos?|cuencos?|jarras?|tazas?|mugs?|vasos?|fuentes?|posavasos|manteles?|"
    r"cortinas?|persianas?|mesas?|sillas?|muebles?|sofas?|camas?|colchones?|almohadas?|"
    r"sabanas?|cobijas?|edredones?|toallas?|tapetes?|alfombras?|lamparas?|cojines?|"
    r"cuadros?|espejos?|floreros?|jarrones?|camisas?|camisetas?|pantalones?|jeans?|"
    r"vestidos?|faldas?|chaquetas?|zapatos?|sandalias?|bolsos?|mochilas?|morrales?|"
    r"maletas?|billeteras?|carteras?|gorras?|sombreros?|ollas?|sartenes?|vajillas?)\b")
_EXPLICIT_TOBACCO_PRODUCT_RE = re.compile(
    r"\b(?:cigarrillos?|cigarillos?|cigarros?|cajetillas?|vapes?|vapers?|vapeador(?:es)?|"
    r"e ?liquids?|pods?|terea|heets|heatsticks?)\b|"
    r"\b(?:nicotine|nic) pouches?\b|bols(?:a|as|ita|itas) de nicotina|"
    r"\d[\d .]*\s*(?:k\s*)?(?:puffs?|pufs?|aspiraciones?|caladas?)\b")
# 4) Tobacco-containing oral pouches (snus / "tab pouches") versus tobacco-free nicotine pouches.
_TOBACCO_ORAL_POUCH_RE = re.compile(
    r"\bsnus\b|\btab pouch(?:es)?\b|\btobacco pouch(?:es)?\b|\bpouch(?:es)? de tabaco\b")
_TOBACCO_FREE_POUCH_RE = re.compile(
    r"\bnicotine pouch(?:es)?\b|\bnic pouch(?:es)?\b|"
    r"bols(?:a|as|ita|itas) de nicotina|pouches? de nicotina|"
    r"tobacco ?free|sin tabaco|libre de tabaco|all ?white")

# A smoking pipe (device) is paraphernalia, but "tabaco para pipa" (real pipe tobacco) is in scope,
# so demote a 'pipa' only when the name does not also assert tobacco.
_PIPE_DEVICE_RE = re.compile(r"\bpipas?\b")
# Genuine tobacco product aisles -> product_type.
_CATALOG_AISLE_TYPES = (
    (re.compile(r"pouch|bolsa.*nicotina|nicotine pouch|snus"), "nicotine_pouch"),
    (re.compile(r"calentad|heated|iluma|heets|terea"), "heated_tobacco"),
    (re.compile(r"vaporiz|vapeo|\bvape"), "vape"),
    (re.compile(r"cigarrillo|cigarr"), "cigarette"),
    (re.compile(r"tabaco|nicotina"), "cigarette"),
)


# A positive nicotine/vape/cigarette signal (generic cue OR a real brand). Required for the aisle
# promotion so head-shop paraphernalia (glass pipes, dry-herb vaporizers) shelved in a vape aisle are
# not swept in just for being on that shelf.
_NICOTINE_SIGNAL_RE = re.compile(
    r"puff|\d\s?mg\b|\d\s?%|\bpod|boxpod|\bvape|vaper|vapead|cigarrill|cigarro|cajetill|nicotin|"
    r"bolsa de nic|\bpouch|dispositivo|desechable|disposable|e ?liquid|\d\s?ml\b|\bsalt|snus|"
    r"heets|terea|iluma|\d+\s?k\b|"
    r"marlboro|lucky|rothmans|chesterfield|\bl m\b|\bl and m\b|kool|\bcamel|pielroja|mustang|"
    r"\bcaribe\b|\bderby|belmont|\bkent\b|dunhill|parliament|\bbaron\b|"
    r"\bvelo\b|waka|glucloud|\bfume|krew|oxbar|elf ?bar|lost mary|vaporesso|voopoo|geekvape|\bsmok\b|"
    r"\bzyn\b|\bbang\b|puff ?bar|\bjuul|vuse|\bpyne|humo azul|scarlet")
_STUDY_NICOTINE_SIGNAL_RE = re.compile(
    r"\d[\d .]*\s*(?:k\s*)?(?:puffs?|pufs?|aspiraciones?)\b|\bpod|boxpod|\bvape|vaper|"
    r"vapead|cigarrill|cigarro|"
    r"cajetill|nicotin|bolsa de nic|\bpouch|dispositivo|desechable|disposable|\be ?liquids?\b|"
    r"\bsalt|snus|heets|terea|iluma|"
    r"marlboro|lucky|rothmans|chesterfield|\bl m\b|\bl and m\b|kool|\bcamel|pielroja|mustang|"
    r"\bcaribe\b|\bderby|belmont|\bkent\b|dunhill|parliament|\bbaron\b|"
    r"\bvelo\b|waka|glucloud|\bfume|krew|oxbar|elf ?bar|lost mary|vaporesso|voopoo|geekvape|\bsmok\b|"
    r"\bzyn\b|\bbang\b|puff ?bar|\bjuul|vuse|\bpyne|humo azul|scarlet|"
    r"stlth|life pod|glucloud|lophty|extre bar|litpod|spaceman sp\d{4,6}|\d+\s?k\b|"
    r"\brefill\b|\bcartucho\b")


def _structured_vape_evidence(row: dict) -> tuple[int | None, bool, bool, bool]:
    """Return (puffs, is_pod, disposable, has_vaporizer_type) from Rappi attributes."""
    value = row.get("attributes_json")
    if isinstance(value, dict):
        attributes = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            parsed = {}
        attributes = parsed if isinstance(parsed, dict) else {}
    else:
        attributes = {}
    raw_puffs = attributes.get("puffs")
    try:
        puffs = int(float(str(raw_puffs).replace(",", ".")))
    except (TypeError, ValueError):
        puffs = None
    if puffs is not None and not 100 <= puffs <= 200_000:
        puffs = None
    vaporizer_type = _normalize(attributes.get("vaporizer_type"))
    return (
        puffs,
        _truthy(attributes.get("is_pod")),
        "desechable" in vaporizer_type or "disposable" in vaporizer_type,
        bool(vaporizer_type),
    )


def _has_vape_identity_signal(name: str) -> bool:
    return bool(
        not _EXPLICIT_NON_VAPE_TOBACCO_RE.search(name)
        and (_VAPE_IDENTITY_RE.search(name)
             or _KNOWN_VAPE_BRAND_RE.search(name)
             or re.search(r"\b\d+(?:[.,]\d+)?\s*mg\b", name))
    )


def _is_standalone_heated_device(name: str) -> bool:
    """IQOS/ILUMA hardware, preserving consumables and explicit welcome kits.

    Definitive consumables and welcome kits win first. Hardware nouns win over a bare
    ``stick`` token, so an ``IQOS Stick Holder`` cannot masquerade as consumable tobacco.
    Accessory titles (chargers, cases) fall through to the ordinary paraphernalia demote.
    """
    if not _HEATED_BRAND_RE.search(name):
        return False
    if _HEATED_WELCOME_KIT_RE.search(name):
        return False
    if _HEATED_CASE_OF_PACKS_RE.search(name):
        return False
    if _HEATED_ENGLISH_ACCESSORY_RE.search(name):
        return True
    if _HEATED_DEFINITIVE_CONSUMABLE_RE.search(name):
        return False
    if _HEATED_DEVICE_TERM_RE.search(name):
        return True
    if _HEATED_BARE_STICK_RE.search(name):
        return False
    return bool(_HEATED_MODEL_RE.search(name) and not _ACCESSORY_NAME_RE.search(name))


def _has_independent_vape_identity(name: str) -> bool:
    """Vape identity that does not rely on a bare mg dose (which edibles also carry)."""
    return bool(
        _EXPLICIT_VAPE_IDENTITY_RE.search(name)
        or _EXPLICIT_VAPE_CAPACITY_RE.search(name)
        or (_KNOWN_VAPE_BRAND_RE.search(name)
            and _SAFE_VAPE_MODEL_CAPACITY_RE.search(name))
        or (_GENERIC_VAPE_LIQUID_RE.search(name) and _VOLUME_ML_RE.search(name))
    )


def _is_edible_collision(name: str) -> bool:
    """Gummy/edible product carrying an mg dose (or titled as a gummy) with no vape identity."""
    if _GOMA_MAGICA_RE.search(name):
        return True
    gummy = _GUMMY_TOKEN_RE.search(name)
    if not gummy:
        return False
    is_gummy_product = (bool(_MG_DOSE_RE.search(name))
                        or bool(re.match(
                            r"^\s*(?:goma|gomas|gomita|gomitas|gummy|gummies|gummys)\b",
                            name)))
    return is_gummy_product and not _has_independent_vape_identity(name)


def _is_homeware_context_collision(row: dict, name: str) -> bool:
    """A context-required brand hit (Camel/Master/Kent/Box...) on a homeware/dishware title.

    Requires an explicit homeware noun and no actual tobacco/nicotine product noun. Weak
    style, flavour and pack-size words do not turn a mug or bowl into a tobacco product.
    """
    raw_flags = row.get("flags") or []
    if isinstance(raw_flags, str):
        raw_flags = [value for value in raw_flags.split("|") if value]
    context_confirmed = (row.get("method") == "keyword_context_confirmed"
                         or any(str(flag).startswith("context_confirmed:")
                                for flag in raw_flags))
    if not context_confirmed:
        return False
    if not _STUDY_HOMEWARE_NOUN_RE.search(name):
        return False
    if _EXPLICIT_TOBACCO_PRODUCT_RE.search(name):
        return False
    # Hardware and paraphernalia titles keep their own demote route (1b), not this one.
    if _NONTOBACCO_DEMOTE_RE.search(name) or _ACCESSORY_NAME_RE.search(name):
        return False
    return True


def _explicit_vape_product_type(name: str) -> str | None:
    """Return a vape subtype only when the title itself proves a vape product."""
    if (re.search(r"\be ?liquids?\b", name)
            or (_GENERIC_VAPE_LIQUID_RE.search(name) and _VOLUME_ML_RE.search(name))):
        return "vape_liquid"
    if re.search(r"\b(?:boxpod|pods?|refill|cartucho)\b", name):
        return "vape_pod"
    if (_EXPLICIT_VAPE_CAPACITY_RE.search(name)
            or (re.search(r"\b(?:desechable|disposable)\b", name)
                and re.search(r"\b(?:vape|vaper|vapeador)\b", name))):
        return "vape_disposable"
    if re.search(r"\b(?:vape|vapes|vaper|vapers|vapeador|vapeadores)\b", name):
        return "vape"
    return None


def _is_tobacco_oral_pouch(name: str) -> bool:
    """Snus / tobacco 'tab pouches' that are not marketed as tobacco-free nicotine pouches."""
    return bool(_TOBACCO_ORAL_POUCH_RE.search(name)
                and not _TOBACCO_FREE_POUCH_RE.search(name))


def _trusted_vape_retail_identity(row: dict) -> bool:
    return bool(
        _normalize(row.get("store_name")) == "vapershito candy"
        and str(row.get("retail_id") or "").lower().startswith("vppolanquirri")
    )


def _has_finished_vape_evidence(row: dict, name: str) -> bool:
    puffs, _, disposable, _ = _structured_vape_evidence(row)
    store = _normalize(row.get("store_name"))
    store_capacity = (re.search(r"\bvapers?\b|\bvape", store)
                      and re.search(r"\b\d{1,3}\s*k\b", name))
    structured_finished = (puffs or disposable) and _has_vape_identity_signal(name)
    return bool(structured_finished or _EXPLICIT_VAPE_CAPACITY_RE.search(name)
                or _KNOWN_VAPE_MODEL_RE.search(name)
                or (_KNOWN_VAPE_BRAND_RE.search(name)
                    and _VAPE_MODEL_CAPACITY_RE.search(name))
                or store_capacity or _trusted_vape_retail_identity(row))


def _study_collision(name: str) -> bool:
    """Study-only non-nicotine collision: reviewed search collisions plus edible products."""
    return bool(_STUDY_NONTOBACCO_DEMOTE_RE.search(name) or _is_edible_collision(name))


def _study_kit_collision(name: str) -> bool:
    """Collisions that disqualify a title from being read as a complete vape kit."""
    return bool(_STUDY_KIT_COLLISION_RE.search(name) or _is_edible_collision(name))


def _is_complete_vape_bundle(row: dict, name: str) -> bool:
    if (_KIT_EXCLUSION_RE.search(name) or _study_kit_collision(name)
            or _HARD_VAPE_COMPONENT_RE.search(name)):
        return False
    finished_evidence = _has_finished_vape_evidence(row, name)
    explicit_puffs = _EXPLICIT_VAPE_CAPACITY_RE.search(name)
    system_cue = _VAPE_SYSTEM_RE.search(name)
    bundle_header = re.search(r"\b(?:kit|combo|pack)\b", name)
    bundle_cue = bool(
        (bundle_header and system_cue)
        or (re.search(r"\b(?:refill|cartucho|repuesto)\b", name) and finished_evidence)
    )
    integrated_battery = (re.search(r"\bbateria\b", name)
                          and (explicit_puffs
                               or (bundle_header and system_cue)
                               or re.search(
                                   r"\bstlth loop\b(?!\s+(?:\d+\s+)?bateria\b).+\bbateria\b|"
                                   r"\bcombo stlth\b.+\b\d+\s*k\b.+\bbateria\b",
                                   name)))
    vape_type = str(row.get("product_type") or "").startswith("vape")
    return bool((bundle_cue or integrated_battery)
                and (vape_type or _STUDY_NICOTINE_SIGNAL_RE.search(name))
                and (finished_evidence or (bundle_header and system_cue)
                     or integrated_battery))


def _has_integrated_vape_coil(row: dict, name: str) -> bool:
    """Keep a finished vape whose title describes its built-in dual-mesh coil."""
    return bool(str(row.get("product_type") or "").startswith("vape")
                and re.match(r"vape\b", name)
                and re.search(r"\bdual mesh coil\b", name)
                and not _study_collision(name)
                and not _study_kit_collision(name))


def _catalog_aisle_type(section: str) -> str | None:
    """Product-type for a genuine store tobacco aisle; None for accessory aisles or non-tobacco."""
    if not section or _ACCESSORY_SECTION_RE.search(section):
        return None
    for rx, ptype in _CATALOG_AISLE_TYPES:
        if rx.search(section):
            return ptype
    return None


def _promoted_product_type(name: str, section: str, study_mode: bool = False) -> str:
    """Best product_type for a catalog-aisle promotion: infer from the name, then fall back to the aisle."""
    patterns = []
    if study_mode:
        patterns.append((re.compile(r"\bpuros?\b|\bpuritos?\b|cafe creme|handelsgold|"
                                    r"\bmontecristo\b|\bpartagas\b"), "cigar"))
    patterns.extend((
        (re.compile(r"\bpouch|bolsas? de nicotina|nicotine pouch|snus"), "nicotine_pouch"),
        (re.compile(r"iluma|heets|terea|heated|calentad"), "heated_tobacco"),
    ))
    if study_mode:
        patterns.append((re.compile(
            r"\b(?:e ?liquids?|liquido)\b.*\d+(?:[.,]\d+)?\s*ml\b"), "vape_liquid"))
    patterns.extend((
        (re.compile(r"\bpod|boxpod|capsula"), "vape_pod"),
        (re.compile(
            r"puff|desechable|disposable"
            + (r"|\bpufs?\b|aspiraciones?|"
               r"\b(?:fume pro|oxbar|vice box|dojo|nexa)\b.*\d+(?:[.,]\d+)?\s*k\b"
               if study_mode else "")),
         "vape_disposable"),
        (re.compile(r"vape|vaper|vaporiz"), "vape"),
        (re.compile(r"cigarrillo|cigarro|cajetilla"), "cigarette"),
    ))
    for rx, ptype in patterns:
        if rx.search(name):
            return ptype
    return _catalog_aisle_type(section) or "cigarette"


def _promoted_vape_product_type(row: dict, name: str, section: str) -> str:
    product_type = _promoted_product_type(name, section, study_mode=True)
    _, is_pod, disposable, _ = _structured_vape_evidence(row)
    if product_type == "vape" and is_pod:
        return "vape_pod"
    if product_type == "vape" and (disposable or _KNOWN_VAPE_MODEL_RE.search(name)):
        return "vape_disposable"
    return product_type if product_type.startswith("vape") else "vape_disposable"


def _is_weighted_loose_tobacco(row: dict) -> bool:
    """Return true when Rappi sells the row by tobacco weight rather than by stick."""
    name = _normalize(row.get("name"))
    if (re.search(r"\b\d{1,3}\s*'?s\b", name)
            or re.search(
                r"\b\d{1,3}\s*(?:u|un|und|uds|unidades?|cigarrillos?|cajetillas?)\b",
                name)):
        return False
    unit = _normalize(row.get("unit_price_unit"))
    pack = _normalize(row.get("pack_format_raw"))
    return (unit in {"g", "gr", "gramo", "gramos"}
            or bool(re.search(r"\b\d+(?:[.,]\d+)?\s*(?:g|gr|grs|gramos?)\b", pack)))


_LEX = None


def _lex():
    global _LEX
    if _LEX is None:
        _LEX = load_lexicon()
    return _LEX


def apply_overrides(row: dict, study_mode: bool = False) -> dict:
    lex = _lex()
    flags = list(row.get("flags") or [])
    primary = row.get("primary_class") or "out_of_scope"

    name = _normalize(row.get("name"))
    brand = _normalize(row.get("brand"))
    name_brand = [("name", name), ("brand", brand)]

    # Study-only scope boundaries. Heated-device hardware is retained in the offline
    # classification under a non-exported subtype. Tobacco-containing oral pouches are likewise
    # kept for review but are not nicotine pouches, which are tobacco-leaf-free by study design.
    if (study_mode and _HEATED_WELCOME_KIT_RE.search(name)
            and re.search(r"\b(?:iqos|iluma)\b", name)
            and "study_heated_welcome_kit" not in flags):
        flags.append("study_heated_welcome_kit")
    if study_mode and _is_standalone_heated_device(name):
        row["primary_class"] = "out_of_scope"
        row["product_type"] = "heated_device"
        row["confidence"] = "high"
        row["method"] = "study_product_boundary"
        row["rationale"] = "standalone heated-tobacco device body"
        if "study_heated_device" not in flags:
            flags.append("study_heated_device")
        row["flags"] = flags
        return row
    explicit_snus_vape_type = (
        _explicit_vape_product_type(name)
        if study_mode and _TOBACCO_ORAL_POUCH_RE.search(name)
        else None
    )
    if explicit_snus_vape_type:
        row["primary_class"] = "tobacco"
        row["product_type"] = explicit_snus_vape_type
        row["confidence"] = "high"
        row["method"] = "study_product_boundary"
        row["rationale"] = "explicit vape identity overrides snus flavour wording"
        if "study_snus_vape_identity" not in flags:
            flags.append("study_snus_vape_identity")
        primary = "tobacco"
    elif (study_mode and _is_tobacco_oral_pouch(name)
          and not _is_edible_collision(name)):
        row["primary_class"] = "tobacco"
        row["product_type"] = "smokeless_tobacco"
        row["confidence"] = "high"
        row["method"] = "study_product_boundary"
        row["rationale"] = "tobacco-containing oral pouch outside nicotine-pouch family"
        if "study_tobacco_pouch" not in flags:
            flags.append("study_tobacco_pouch")
        row["flags"] = flags
        return row
    if study_mode and _is_homeware_context_collision(row, name):
        row["primary_class"] = "out_of_scope"
        row["confidence"] = "high"
        row["method"] = "study_product_boundary"
        row["rationale"] = "context brand on a homeware/dishware title without product evidence"
        for flag in ("nontobacco_demote", "study_homeware_collision"):
            if flag not in flags:
                flags.append(flag)
        row["flags"] = flags
        return row

    complete_vape_kit = study_mode and _is_complete_vape_bundle(row, name)
    integrated_vape_coil = study_mode and _has_integrated_vape_coil(row, name)
    finished_vape_evidence = study_mode and _has_finished_vape_evidence(row, name)
    verified_finished_vape = bool(
        finished_vape_evidence
        and not _study_collision(name)
        and not _study_kit_collision(name)
        and not _HARD_VAPE_COMPONENT_RE.search(name)
    )

    # 1) Hard floor: paraphernalia / candy can never be tobacco.
    if ("candy_cigarette" in flags
            or ("tobacco_paraphernalia" in flags
                and not complete_vape_kit and not integrated_vape_coil
                and not verified_finished_vape)):
        row["primary_class"] = "out_of_scope"
        row["flags"] = flags
        return row

    # 1b) Universal non-tobacco demote. Stage A's keyword_strong / keyword_context paths promote on a
    #     bare word ('vape', 'blunt', 'box') with no accessory guard, so head-shop hardware, empty
    #     rolling material and tobacco-free wraps arrive here mislabeled tobacco. Demote any such row --
    #     no matter which method promoted it -- plus anything shelved in an accessories/papel/lighter
    #     aisle, and metal/glass smoking pipes (but not real pipe tobacco).
    if primary == "tobacco":
        section = _normalize(row.get("menu_section"))
        if study_mode:
            accessory_only = (_ACCESSORY_SECTION_RE.search(section)
                              and ((_ACCESSORY_NAME_RE.search(name) and not complete_vape_kit)
                                   or not _FINISHED_PRODUCT_RE.search(name)))
            kit_override = (complete_vape_kit and not _KIT_EXCLUSION_RE.search(name)
                            and not _is_edible_collision(name))
            hardware_only = ((_NONTOBACCO_DEMOTE_RE.search(name)
                              or _study_collision(name))
                             and not kit_override and not integrated_vape_coil)
        else:
            accessory_only = _ACCESSORY_SECTION_RE.search(section)
            hardware_only = _NONTOBACCO_DEMOTE_RE.search(name)
        if (hardware_only or accessory_only
                or (_PIPE_DEVICE_RE.search(name) and "tabaco" not in name)):
            row["primary_class"] = "out_of_scope"
            if "nontobacco_demote" not in flags:
                flags.append("nontobacco_demote")
            row["flags"] = flags
            return row

    # 1c) Rappi's structured vape attributes or an explicit advertised puff/model capacity are
    #     product-level evidence. They can recover a finished device even when a merchant files it
    #     under a generic technology/accessory aisle. Collision and hardware rules remain hard gates.
    if (study_mode and row.get("primary_class") != "tobacco" and verified_finished_vape
            and (not _ACCESSORY_NAME_RE.search(name)
                 or complete_vape_kit
                 or _EXPLICIT_VAPE_CAPACITY_RE.search(name))):
        aisle = _normalize(row.get("catalog_menu_section") or row.get("menu_section"))
        row["primary_class"] = "tobacco"
        row["product_type"] = _promoted_vape_product_type(row, name, aisle)
        row["confidence"] = "high"
        row["method"] = "study_vape_evidence"
        row["rationale"] = (
            "reviewed vape retailer SKU identity"
            if _trusted_vape_retail_identity(row)
            else "structured vape attributes or advertised device capacity"
        )
        flags = [flag for flag in flags if flag != "study_type_unresolved"]
        if "study_vape_evidence" not in flags:
            flags.append("study_vape_evidence")
        primary = "tobacco"

    # 2) Defensive FN net: 18+ flag AND an unambiguous tobacco term in the name,
    #    but a non-tobacco label -> promote. Do NOT re-promote furniture/home-goods that
    #    Stage A demoted (e.g. a plastic table in the wood colour "Madeira Tabaco"), and
    #    require a DISTINCTIVE term (not the bare colour words 'tabaco'/'habano').
    _AMBIG_COLOUR = {"tabaco", "tabacos", "habano", "habanos"}
    if (primary != "tobacco" and _truthy(row.get("has_antismoking"))
            and "home_goods_collision" not in flags):
        hit = _first_hit(name_brand, lex.get("tobacco_safe"))
        study_hit_allowed = (not study_mode
                             or (not _study_collision(name)
                                 and (hit and hit[1] not in {"vaporizador", "vaporizadores"}
                                      or _STUDY_NICOTINE_SIGNAL_RE.search(name))))
        if hit and hit[1] not in _AMBIG_COLOUR and study_hit_allowed:
            row["primary_class"] = "tobacco"
            row["confidence"] = "high"
            row["method"] = "stage_c_antismoking"
            row.setdefault("rationale", "")
            row["rationale"] = "has_antismoking + tobacco name term"
            if study_mode and not row.get("product_type"):
                aisle = _normalize(row.get("catalog_menu_section") or row.get("menu_section"))
                row["product_type"] = _promoted_product_type(name, aisle, study_mode=True)
                flags = [flag for flag in flags if flag != "study_type_unresolved"]
            if "override:has_antismoking" not in flags:
                flags.append("override:has_antismoking")

    # 3) Trust the store's real aisle. Both search and catalog carry the product's OWN category
    #    (`category_name`) as `menu_section`, so a product the store shelves under Cigarrillos /
    #    Vaporizadores / Pouches is a nicotine product -- the name-only lexicon just misses unbranded
    #    pods ("15000 Puffs 5%") and plural-pouch phrasings. `catalog_menu_section` (set by collect.union
    #    for every catalog-covered product) is preferred because it survives the search-wins dedup and is
    #    the store's authoritative aisle; the row's own `menu_section` is the fallback. The gate is what
    #    keeps this precise, NOT the source: a genuine tobacco aisle AND a positive nicotine signal AND
    #    NOT an accessory/paraphernalia/hardware/tobacco-free name. The old 'tabaco'-mis-shelf false
    #    positives (paint, wood, food) have no nicotine signal, so they stay out.
    if row.get("primary_class") != "tobacco":
        aisle = _normalize(row.get("catalog_menu_section") or row.get("menu_section"))
        signal_re = _STUDY_NICOTINE_SIGNAL_RE if study_mode else _NICOTINE_SIGNAL_RE
        study_demote = study_mode and _study_collision(name)
        complete_vape_kit = study_mode and _is_complete_vape_bundle(row, name)
        aisle_type = _catalog_aisle_type(aisle)
        _, _, _, structured_vape_type = _structured_vape_evidence(row)
        structured_vape_aisle = bool(
            study_mode and aisle_type == "vape" and structured_vape_type
            and _has_vape_identity_signal(name))
        vape_liquid_dose = bool(
            study_mode and aisle_type == "vape" and _truthy(row.get("has_antismoking"))
            and re.search(r"\b\d+(?:[.,]\d+)?\s*ml\b", name)
            and re.search(r"\b\d+(?:[.,]\d+)?\s*mg\b|\b(?:liquido|liquid|salt|kit)\b",
                          name))
        vape_nicotine_dose = bool(
            study_mode and aisle_type == "vape"
            and re.search(r"\b\d+(?:[.,]\d+)?\s*mg\b", name)
            and not _EXPLICIT_NON_VAPE_TOBACCO_RE.search(name))
        explicit_v2_liquid = bool(
            study_mode and aisle_type == "vape" and _STUDY_V2_LIQUID_RE.search(name))
        pouch_dose = (study_mode and aisle_type == "nicotine_pouch"
                      and re.search(r"\b\d+(?:[.,]\d+)?\s*mg\b", name))
        cigarette_identity = (
            study_mode
            and aisle_type == "cigarette"
            and _truthy(row.get("has_antismoking"))
            and (re.search(r"\b\d+\s*(?:u|un|und|uds|unidades?)\b", name)
                 or re.search(r"\bamerican spirit\b", name))
        )
        if (aisle_type and (signal_re.search(name) or pouch_dose or cigarette_identity
                            or structured_vape_aisle or vape_liquid_dose
                            or vape_nicotine_dose or explicit_v2_liquid)
                and (not _ACCESSORY_NAME_RE.search(name)
                     or complete_vape_kit or integrated_vape_coil)
                and (not _NONTOBACCO_DEMOTE_RE.search(name)
                     or complete_vape_kit or integrated_vape_coil)
                and (not study_demote or complete_vape_kit)
                and "non_nicotine_herbal" not in flags):
            row["primary_class"] = "tobacco"
            row["confidence"] = "high"
            row["method"] = "catalog_section"
            row["rationale"] = f"catalog store aisle {aisle!r}"
            if not row.get("product_type"):
                row["product_type"] = ("vape_liquid" if (vape_liquid_dose
                                                         or explicit_v2_liquid)
                                       else _promoted_product_type(
                                           name, aisle, study_mode=study_mode))
            if "catalog_section" not in flags:
                flags.append("catalog_section")

    # Product-level vape evidence is stronger than a noisy aisle or a generic
    # tobacco word in the title. This also corrects structured disposable/pod
    # rows that Stage A initially labels as cigarettes or loose tobacco.
    if (study_mode and row.get("primary_class") == "tobacco"
            and not str(row.get("product_type") or "").startswith("vape")
            and row.get("product_type") not in {"nicotine_pouch", "heated_tobacco"}
            and verified_finished_vape):
        aisle = _normalize(row.get("catalog_menu_section") or row.get("menu_section"))
        row["product_type"] = _promoted_vape_product_type(row, name, aisle)
        if "study_vape_capacity_type" not in flags:
            flags.append("study_vape_capacity_type")

    # A few retailers title rolling tobacco with a cigarette brand or even the
    # word "cigarrillos". Rappi's gram-denominated unit is the decisive cue.
    if (study_mode and row.get("primary_class") == "tobacco"
            and row.get("product_type") == "cigarette"
            and _is_weighted_loose_tobacco(row)):
        row["product_type"] = "rolling_tobacco"
        if "study_weighted_loose_tobacco" not in flags:
            flags.append("study_weighted_loose_tobacco")

    row["flags"] = flags
    return row
