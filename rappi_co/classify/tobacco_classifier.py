"""Rappi Colombia self-contained tobacco/nicotine classifier (Stage A).

Single in-scope class (`tobacco`); everything else is `out_of_scope`. Dependency-light
(stdlib + PyYAML), and aware of both false positives and false negatives. Precedence is
fixed by an adversarial regression set:

  1. candy / chocolate "cigarrillos"            -> out_of_scope (tagged)
  2. STRONG tobacco (real brand / product term) -> tobacco  (beats paraphernalia,
       so a cigarette/rolling-tobacco COMBO bundled with papers/lighter stays in)
  3. NRT / cessation w/ nicotine                -> tobacco (flag nrt)
  4. herbal / non-nicotine cessation            -> out_of_scope
  5. tobacco-scent home fragrance               -> out_of_scope
  6. paraphernalia (no strong signal)           -> out_of_scope (tagged)
  7. generic tobacco term (cigarrillo/tabaco)   -> tobacco
  8. collision brand (camel/box/derby/...)      -> tobacco only with corroboration,
       else logged oos_context_unconfirmed (recall-safe, never silently dropped)
  9. strict tobacco aisle, nothing else         -> out_of_scope (review candidate)
 10. has_antismoking, no keyword               -> out_of_scope (recall candidate)
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

# repo-root config/ (rappi_co/classify/ -> rappi_co/ -> repo root)
_DEFAULT_LEXICON = Path(__file__).resolve().parent.parent.parent / "config" / "keywords_co.yml"

_WORD_SEP_RE = re.compile(r"[\s\-_/&,.()\[\]+:;|]+")


# --------------------------------------------------------------------------- #
# Normalization + matching
# --------------------------------------------------------------------------- #
def _normalize(s: Optional[str]) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(s))
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return _WORD_SEP_RE.sub(" ", no_accents.lower()).strip()


@lru_cache(maxsize=None)
def _keyword_pattern(kw: str) -> re.Pattern:
    return re.compile(r"(?:^|\W)" + re.escape(kw) + r"(?:\W|$)")


def _matches(text: str, kw: str) -> bool:
    if not kw or not text:
        return False
    return bool(_keyword_pattern(kw).search(text))


def _first_hit(fields: list[tuple[str, str]], kw_list) -> Optional[tuple[str, str]]:
    for kw_raw in kw_list or []:
        kw = _normalize(kw_raw)
        if not kw:
            continue
        for fname, ftext in fields:
            if _matches(ftext, kw):
                return (fname, kw)
    return None


def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "y", "t", "si", "sí")
    return bool(v) if v is not None else False


# --------------------------------------------------------------------------- #
# Result type
# --------------------------------------------------------------------------- #
@dataclass
class TobaccoResult:
    primary_class: str
    product_type: Optional[str] = None
    confidence: str = "medium"
    method: str = "keyword"
    rationale: str = ""
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"primary_class": self.primary_class, "product_type": self.product_type,
                "confidence": self.confidence, "method": self.method,
                "rationale": self.rationale, "flags": list(self.flags)}


# --------------------------------------------------------------------------- #
# Lexicon
# --------------------------------------------------------------------------- #
def load_lexicon(path: Optional[str | Path] = None) -> dict:
    p = Path(path) if path else _DEFAULT_LEXICON
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_market_lexicon(country: str, config_dir: Optional[str | Path] = None) -> dict:
    """Extend the shared Spanish lexicon with one study market's reviewed brands."""
    from rappi_co.configs import brand_variants, load_study_profile

    root = Path(__file__).resolve().parent.parent.parent
    profile = load_study_profile(country, Path(config_dir) if config_dir else root / "config" / "study")
    lex = load_lexicon()
    lex["_study_market"] = country
    product_types = lex.setdefault("product_type_map", {})
    # A bare "vaporizador" is also a household spray bottle or clothes steamer.
    # In study mode, require another nicotine signal (brand, pod, puff count, etc.).
    ambiguous_vaporizer = {"vaporizador", "vaporizadores"}
    lex["tobacco_safe"] = [
        term for term in (lex.get("tobacco_safe") or [])
        if _normalize(term) not in ambiguous_vaporizer
    ]
    product_types["cigar"] = [
        term for term in (product_types.get("cigar") or [])
        if _normalize(term) not in {"cigarro", "cigarros"}
    ]
    for term in ("cigarro", "cigarros"):
        if term not in {_normalize(value) for value in product_types.get("cigarette", [])}:
            product_types.setdefault("cigarette", []).append(term)
    product_types["nicotine_pouch"] = [
        term for term in (product_types.get("nicotine_pouch") or [])
        if _normalize(term) not in {"pouch", "pouches"}
    ]
    for term in ("pouch", "pouches"):
        if term not in {_normalize(value) for value in lex.get("tobacco_context_required", [])}:
            lex.setdefault("tobacco_context_required", []).append(term)
    # Retailers throughout the study markets commonly spell the product noun
    # "vaper" rather than vape/vapeador. Keep this extension study-only so the
    # original Colombia classifier remains unchanged.
    for term in ("vaper", "vapers", "extre bar"):
        if term not in {_normalize(value) for value in lex.get("tobacco_safe", [])}:
            lex.setdefault("tobacco_safe", []).append(term)
        if term not in {
            _normalize(value)
            for value in lex.setdefault("product_type_map", {}).setdefault("vape", [])
        }:
            lex["product_type_map"]["vape"].append(term)
    by_brand: dict[str, set[str]] = {}
    for entry in profile["brand_terms"]:
        for variant in brand_variants(entry):
            by_brand.setdefault(_normalize(variant), set()).add(entry["category"])

    type_map = {
        "nicotine_pouches": "nicotine_pouch",
        "electronic_cigarettes": "vape",
        "heated_tobacco": "heated_tobacco",
        "cigarettes": "cigarette",
    }
    lex["_study_brand_type_map"] = {
        variant: type_map[next(iter(categories))]
        for variant, categories in by_brand.items()
        if len(categories) == 1
    }
    for entry in profile["brand_terms"]:
        for variant in brand_variants(entry):
            normalized = _normalize(variant)
            target = ("tobacco_safe" if entry["match"] == "distinctive"
                      else "tobacco_context_required")
            other = "tobacco_context_required" if target == "tobacco_safe" else "tobacco_safe"
            lex[other] = [term for term in (lex.get(other) or [])
                          if _normalize(term) != normalized]
            if normalized not in {_normalize(term) for term in (lex.get(target) or [])}:
                lex.setdefault(target, []).append(variant)
            if len(by_brand[normalized]) == 1:
                product_type = type_map[entry["category"]]
                mapped = lex.setdefault("product_type_map", {}).setdefault(product_type, [])
                if normalized not in {_normalize(term) for term in mapped}:
                    mapped.append(variant)
    return lex


def _strong_terms(lex: dict) -> list[str]:
    """tobacco_safe minus the generic (low-distinctiveness) terms."""
    generic = {_normalize(g) for g in (lex.get("tobacco_generic") or [])}
    return [kw for kw in (lex.get("tobacco_safe") or []) if _normalize(kw) not in generic]


def _detect_product_type(tob_text: str, lex: dict) -> Optional[str]:
    study_hits: list[tuple[int, str]] = []
    for ptype, kws in (lex.get("product_type_map") or {}).items():
        for kw in kws or []:
            normalized = _normalize(kw)
            if _matches(tob_text, normalized):
                if not lex.get("_study_market"):
                    return ptype
                study_hits.append((len(normalized), ptype))
    if study_hits:
        return max(study_hits, key=lambda hit: hit[0])[1]
    return None


def _product_type_for(identity_text: str, section_text: str, lex: dict) -> Optional[str]:
    """Prefer product identity over aisle context when assigning the subtype."""
    if lex.get("_study_market"):
        if (re.search(r"\b(?:luckies|lucky strike)\b.*\btabaco\b", identity_text)
                or re.search(r"\btabaco\b.*\b(?:luckies|lucky strike)\b", identity_text)):
            return "rolling_tobacco"
        if re.search(r"\bmacondo\b", identity_text) and re.search(r"\bcigarros?\b", identity_text):
            return "cigar"
        if re.search(r"\b(?:cafe creme|handelsgold)\b|\bcigarillos? exo\b", identity_text):
            return "cigar"
        if re.search(r"\bcigarro device\b", identity_text):
            return "vape"
        if re.search(r"\b(cohiba|habano|habanos|puros?|robusto)\b", identity_text):
            return "cigar"
        if re.search(r"\b(iqos|terea|heets|iluma)\b|tabaco calentado", identity_text):
            return "heated_tobacco"
        if re.search(r"tabaco (?:para )?armar|para armar cigarr|tabaco de liar|para liar",
                     identity_text):
            return "rolling_tobacco"
        pouch = re.search(r"\bpouch(?:es)?\b", identity_text)
        if pouch and re.search(r"nicotin|\b\d+(?:[.,]\d+)?\s*(?:mg|%)", identity_text):
            return "nicotine_pouch"
        grams = re.search(r"\b\d+(?:[.,]\d+)?\s*(?:g|gr|grs|gramos?)\b", identity_text)
        if grams and ("tabaco" in identity_text or pouch):
            return "rolling_tobacco"
        brand_hits = [
            (len(variant), product_type)
            for variant, product_type in lex.get("_study_brand_type_map", {}).items()
            if _matches(identity_text, variant)
        ]
        brand_type = max(brand_hits, key=lambda hit: hit[0])[1] if brand_hits else None
        identity_type = _detect_product_type(identity_text, lex)
        if brand_type == "cigarette" and identity_type in {None, "rolling_tobacco"}:
            return "cigarette"
        if (identity_type in {None, "cigarette"}
                and re.search(r"\d[\d .,]*\s*(?:k\s*)?(?:puffs?|pufs?|caladas?)\b",
                              identity_text)):
            return "vape_disposable"
        if (identity_type in {None, "cigarette"}
                and re.search(r"\b(?:fume pro|oxbar|vice box)\b.*\d+(?:[.,]\d+)?\s*k\b",
                              identity_text)):
            return "vape_disposable"
        if "tabaco" in identity_text and not identity_type:
            return "rolling_tobacco"
        return identity_type or brand_type or _detect_product_type(section_text, lex)
    return (_detect_product_type(identity_text, lex)
            or _detect_product_type(section_text, lex))


def _study_type_flags(lex: dict, product_type: Optional[str], flags=None) -> list[str]:
    result = list(flags or [])
    if lex.get("_study_market") and not product_type and "study_type_unresolved" not in result:
        result.append("study_type_unresolved")
    return result


# --------------------------------------------------------------------------- #
# Core classification
# --------------------------------------------------------------------------- #
def classify_item(item: dict, lexicon: dict) -> TobaccoResult:
    lex = lexicon
    name = _normalize(item.get("name"))
    brand = _normalize(item.get("brand"))
    section = _normalize(item.get("menu_section"))
    subsection = _normalize(item.get("menu_subsection"))
    has_antismoking = _truthy(item.get("has_antismoking"))

    name_brand = [("name", name), ("brand", brand)]
    all_fields = name_brand + [("subsection", subsection), ("section", section)]
    identity_text = " ".join([name, brand]).strip()
    sec_text = (section + " " + subsection).strip()

    section_is_tobacco = any(
        _matches(sec_text, _normalize(s)) for s in (lex.get("tobacco_sections") or []))

    # Strong/generic signals must come from the product's OWN identity (name/brand),
    # NOT the aisle name — otherwise rolling papers shelved under a "Tabaco para
    # Armar" aisle would inherit the aisle's tobacco term and be promoted.
    strong = _first_hit(name_brand, _strong_terms(lex))
    generic = _first_hit(name_brand, lex.get("tobacco_generic"))
    nrt = _first_hit(name_brand, lex.get("nrt"))

    # 0) HOME GOODS: on the whole catalog (not just tobacco aisles), the brown colour words
    #    'tabaco'/'habano' and the clothes-steamer 'vaporizador de ropa' collide with
    #    furniture/curtains/apparel. If the name carries a home-goods word AND the only
    #    tobacco signal is a colour/appliance term (no distinctive brand, no NRT), it's OOS.
    home_ctx = _first_hit(name_brand, lex.get("non_consumable_context"))
    if home_ctx:
        _AMBIG = {"habano", "habanos", "tabaco", "tabacos", "vaporizador", "vaporizadores"}
        ambiguous = _first_hit(name_brand, list(_AMBIG))
        distinctive = _first_hit(name_brand, [t for t in _strong_terms(lex)
                                              if _normalize(t) not in _AMBIG])
        if ambiguous and not distinctive and not nrt:
            return TobaccoResult("out_of_scope", None, "high", "home_goods_demote",
                                 f"home-goods context '{home_ctx[1]}' + only colour/appliance "
                                 f"term '{ambiguous[1]}'", ["home_goods_collision"])

    # 1) CANDY: explicit marker OR (confection context + a CIGARETTE word + not real
    #    tobacco). Only cigarrillo/cigarro count here — "tabaco sabor chocolate" is
    #    real flavored rolling tobacco, NOT a confection.
    candy_marker = _first_hit(all_fields, lex.get("candy_cigarette_markers"))
    conf_ctx = _first_hit(all_fields, lex.get("confectionery_context"))
    generic_cig = _first_hit(name_brand, ["cigarrillo", "cigarrillos", "cigarillo",
                                          "cigarillos", "cigarro", "cigarros", "cigarito"])
    if candy_marker or (conf_ctx and generic_cig and not strong and not nrt):
        ev = candy_marker[1] if candy_marker else f"{conf_ctx[1]}+{generic_cig[1]}"
        return TobaccoResult("out_of_scope", None, "high", "candy_demote",
                             f"candy/confection cue '{ev}'", ["candy_cigarette"])

    # 2) STRONG tobacco. Generic vape/device words do not override an explicit
    #    accessory signal (for example, "bolsa hermetica vape" or a vape lighter).
    if strong:
        ptype = _product_type_for(identity_text, sec_text, lex)
        flags = _study_type_flags(lex, ptype)
        zero = _first_hit(name_brand, lex.get("zero_nicotine_markers"))
        if zero and (ptype or "").startswith("vape"):
            flags.append("zero_nicotine")
        para = _first_hit(all_fields, lex.get("paraphernalia"))
        if para:
            weak_device_hits = {
                "vape", "vapes", "vapeador", "vapeadores", "vaporizador",
                "vaporizadores", "vaper", "vapers", "vapeo",
            }
            if strong[1] in weak_device_hits:
                return TobaccoResult(
                    "out_of_scope", "paraphernalia", "high", "paraphernalia_demote",
                    f"accessory '{para[1]}' overrides generic device term '{strong[1]}'",
                    ["tobacco_paraphernalia"],
                )
            flags.append("contains_paraphernalia")
        conf = "high" if strong[0] in ("name", "brand") else "medium"
        return TobaccoResult("tobacco", ptype, conf, "keyword_strong",
                             f"strong tobacco '{strong[1]}' ({strong[0]})"
                             + ("; +zero-nic" if "zero_nicotine" in flags else ""),
                             flags)

    # 3) NRT / cessation with nicotine — in scope.
    if nrt:
        return TobaccoResult("tobacco", "nrt", "high", "keyword_nrt",
                             f"NRT/cessation '{nrt[1]}' ({nrt[0]})", ["nrt"])

    # 4) Herbal / non-nicotine cessation (no tobacco AND no nicotine) — out of scope.
    no_nic = _first_hit(all_fields, lex.get("no_nicotine_markers"))
    non_tob = _first_hit(all_fields, lex.get("non_tobacco_context"))
    if no_nic and non_tob:
        return TobaccoResult("out_of_scope", None, "high", "non_nicotine_demote",
                             f"no-nicotine '{no_nic[1]}' + non-tobacco '{non_tob[1]}'",
                             ["non_nicotine_herbal"])

    # 5) Tobacco-scent home fragrance / cosmetic — out of scope.
    scent = _first_hit(all_fields, lex.get("scent_context"))
    if scent and generic and not strong:
        return TobaccoResult("out_of_scope", None, "high", "scent_demote",
                             f"scent context '{scent[1]}' + generic '{generic[1]}'",
                             ["tobacco_scent"])

    # 6) Paraphernalia (no strong tobacco) — out of scope, captured + tagged.
    para = _first_hit(all_fields, lex.get("paraphernalia"))
    if para:
        return TobaccoResult("out_of_scope", "paraphernalia", "high", "paraphernalia_demote",
                             f"paraphernalia '{para[1]}' ({para[0]})", ["tobacco_paraphernalia"])

    # 7) Generic tobacco term in the item's identity.
    if generic:
        ptype = _product_type_for(identity_text, sec_text, lex)
        conf = "high" if generic[0] in ("name", "brand") else "medium"
        return TobaccoResult("tobacco", ptype, conf, "keyword_generic",
                             f"generic tobacco '{generic[1]}' ({generic[0]})",
                             _study_type_flags(lex, ptype))

    # 8) Collision brands — only with corroboration; else logged for recall.
    ctx = _first_hit(name_brand, lex.get("tobacco_context_required"))
    if ctx:
        corroborator = _first_hit(all_fields, lex.get("tobacco_generic_corroborators"))
        signal = ("section" if section_is_tobacco else
                  "has_antismoking" if has_antismoking else
                  (f"corroborator:{corroborator[1]}" if corroborator else None))
        if signal:
            ptype = _product_type_for(identity_text, sec_text, lex) or "cigarette"
            conf = "high" if (section_is_tobacco and ctx[0] in ("name", "brand")) else "medium"
            return TobaccoResult("tobacco", ptype, conf, "keyword_context_confirmed",
                                 f"context brand '{ctx[1]}' confirmed by {signal}",
                                 _study_type_flags(
                                     lex, ptype,
                                     [f"context_confirmed:{signal.split(':')[0]}"]))
        return TobaccoResult("out_of_scope", None, "low", "keyword_context_unconfirmed",
                             f"context brand '{ctx[1]}' uncorroborated",
                             [f"oos_context_unconfirmed:{ctx[1]}"])

    # 9) Aisle membership alone is not product evidence. Live catalog aisles contain
    #    unrelated merchandise, so retain these as review candidates instead of
    #    silently promoting them into the final tobacco dataset.
    if section_is_tobacco:
        reason = (f"; non-consumable cue '{home_ctx[1]}'" if home_ctx else "")
        return TobaccoResult("out_of_scope", None, "low", "section_only_review",
                             f"tobacco aisle without product-level tobacco evidence{reason}",
                             ["oos_section_review"])

    # 10) has_antismoking with no keyword — OOS but flagged for recall review.
    if has_antismoking:
        return TobaccoResult("out_of_scope", None, "low", "keyword_oos",
                             "has_antismoking=True, no tobacco keyword (recall candidate)",
                             ["oos_has_antismoking"])

    # 11) Nothing.
    return TobaccoResult("out_of_scope", None, "medium", "keyword_oos", "no tobacco signal", [])


# --------------------------------------------------------------------------- #
# Batch helper
# --------------------------------------------------------------------------- #
def classify_dataframe(df, lexicon: Optional[dict] = None):
    import pandas as pd
    lex = lexicon or load_lexicon()
    return pd.DataFrame([classify_item(r, lex).as_dict()
                         for r in df.to_dict(orient="records")], index=df.index)
