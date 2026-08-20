"""Regex enrichment for CO tobacco rows: nicotine mg/mL, nicotine %, puff count,
plus pack size and e-liquid volume parsed from the product name.

pure regex, offline. applied per-row by the export step.
"""
from __future__ import annotations

import re
from typing import Optional

_MG_ML = re.compile(r"(\d+(?:[.,]\d+)?)\s*mg\s*/?\s*ml", re.IGNORECASE)
_MG_PER_G = re.compile(r"(\d+(?:[.,]\d+)?)\s*mg\s*/\s*g\b", re.IGNORECASE)
_MG = re.compile(r"(\d+(?:[.,]\d+)?)\s*mg\b", re.IGNORECASE)
_PCT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%", re.IGNORECASE)
_PUFF_CORE = r"puffs?|caladas?|pitadas?|hits?"
_PUFF_UNIT = rf"(?:{_PUFF_CORE})"
_PUFF_STUDY_UNIT = rf"(?:{_PUFF_CORE}|pufs?|aspiraci[oó]n(?:es)?)"
_PUFF = re.compile(
    rf"(?<!\d)(\d{{1,3}}(?:[.,]\d{{3}})+|\d{{3,6}})(?!\d)\s*{_PUFF_UNIT}",
    re.IGNORECASE,
)
_PUFF_K = re.compile(rf"(?<!\d)(\d{{1,3}}(?:[.,]\d+)?)\s*k\s*{_PUFF_UNIT}",
                     re.IGNORECASE)
_PUFF_STUDY = re.compile(
    rf"(?<!\d)(\d{{1,3}}(?:[., ]\d{{3}})+|\d{{3,6}})(?!\d)\s*{_PUFF_STUDY_UNIT}",
    re.IGNORECASE,
)
_PUFF_STUDY_K = re.compile(
    rf"(?<!\d)(\d{{1,3}}(?:[.,]\d+)?)\s*k\s*{_PUFF_STUDY_UNIT}",
    re.IGNORECASE,
)
_PUFF_BARE_K = re.compile(r"(?<!\d)(\d{1,3}(?:[.,]\d+)?)\s*k\b", re.IGNORECASE)
_PUFF_BARE_NUMBER = re.compile(
    r"(?<!\d)(\d{1,3}(?:[., ]\d{3})+|\d{4,6})(?!\d)", re.IGNORECASE)
# Pack size in the name, e.g. "20 Und", "X10", "10 cigarrillos", "cajetilla x20".
_PACK = re.compile(
    r"\b(\d{1,3})\s*(?:und|uds|unidad(?:es)?|cigarrillos?|"
    r"cigarrilos?|cajetillas?|cigs?)\b",
    re.IGNORECASE)
_PACK_STUDY = re.compile(
    r"(?<![\d.,])\b(\d{1,3})\s*(?:u|un|und|unds|uds|unidad(?:es)?|cigarrillos?|"
    r"cigarrilos?|cajetillas?|cigs?)\b",
    re.IGNORECASE)
_PACK_X = re.compile(r"\b[xX]\s?(\d{1,3})\b")
_PACK_X_STUDY = re.compile(
    r"\b[xX]\s?(\d{1,3})(?![.,]\d)(?!\s*\d)(?!\s*(?:g|gr|grs|gramos?|ml)\b)\b",
    re.IGNORECASE,
)
_PACK_X_UNIT_STUDY = re.compile(
    r"\b[xX]\s?(\d{1,3})\s*(?:u|un|und|unds|uds|unidades?)\b", re.IGNORECASE)
_PACK_S = re.compile(r"(?<![\d.,])\b(\d{1,3})\s*['’´]?s\b", re.IGNORECASE)
_CIGARETTE_CARTON = re.compile(
    r"^\s*(\d{1,2})\s*[x×]\s+.*\b(\d{1,3})\s*$", re.IGNORECASE)
# E-liquid volume, e.g. "30ml", "60 mL".
_ML = re.compile(r"(\d+(?:[.,]\d+)?)\s*ml\b", re.IGNORECASE)


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _pack_from_text(text: str, product_type: Optional[str] = None) -> Optional[int]:
    if product_type == "cigarette":
        carton = _CIGARETTE_CARTON.search(text)
        if carton:
            outer, inner = int(carton.group(1)), int(carton.group(2))
            total = outer * inner
            if 2 <= outer <= 50 and 2 <= inner <= 100 and total <= 1000:
                return total
    if product_type:
        patterns = [_PACK_STUDY, _PACK_X_UNIT_STUDY, _PACK_X_STUDY]
        if product_type in {"cigarette", "nicotine_pouch", "heated_tobacco"}:
            patterns.append(_PACK_S)
    else:
        # Keep the original Colombia enrichment semantics when callers do not opt
        # into a study product type.
        patterns = [_PACK, _PACK_X]
    for rx in patterns:
        m = rx.search(text)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 100:
                return n
    return None


def _vol_from_text(text: str) -> Optional[float]:
    m = _ML.search(text)
    if m:
        v = _num(m.group(1))
        if 0 < v <= 10000:
            return v
    return None


def _puff_from_text(text: str, product_type: Optional[str] = None) -> Optional[int]:
    study_vape = str(product_type or "").startswith("vape")
    shorthand = (_PUFF_STUDY_K.search(text) if study_vape else None) or _PUFF_K.search(text)
    if shorthand:
        count = round(_num(shorthand.group(1)) * 1000)
        return count if 100 <= count <= 200_000 else None
    match = (_PUFF_STUDY.search(text) if study_vape else None) or _PUFF.search(text)
    if match:
        count = int(re.sub(r"[,. ]", "", match.group(1)))
        return count if 100 <= count <= 200_000 else None
    if study_vape:
        bare = _PUFF_BARE_K.search(text)
        if bare:
            count = round(_num(bare.group(1)) * 1000)
            return count if 100 <= count <= 200_000 else None
        bare_number = _PUFF_BARE_NUMBER.search(text)
        if bare_number:
            count = int(re.sub(r"[,. ]", "", bare_number.group(1)))
            return count if 1000 <= count <= 200_000 else None
    return None


def enrich_tobacco_fields(name: Optional[str], description: Optional[str] = None,
                          product_type: Optional[str] = None) -> dict:
    text = f"{name or ''} {description or ''}".strip()
    out = {"nicotine_mg_per_ml": None, "nicotine_mg_per_pouch": None, "nicotine_pct": None,
           "nicotine_source": None, "puff_count": None,
           "pack_count": None, "volume_ml": None}
    if not text:
        return out
    out["pack_count"] = _pack_from_text(text, product_type)
    out["volume_ml"] = _vol_from_text(text)

    m = _MG_ML.search(text)
    if m:
        out["nicotine_mg_per_ml"] = _num(m.group(1))
        out["nicotine_source"] = "regex_name"
    else:
        # A bare mg value on a pouch is an amount per pouch, not a liquid concentration.
        # mg/g disambiguation belongs to the study path. Keep calls that omit
        # product_type byte-for-byte compatible with the legacy enrichment.
        m2 = None if product_type and _MG_PER_G.search(text) else _MG.search(text)
        if m2 and ("nicotin" in text.lower() or "mg" in text.lower()):
            tl = text.lower()
            pouch_context = product_type == "nicotine_pouch" or any(term in tl for term in (
                "pouch", "bolsita de nicotina", "bolsitas de nicotina",
                "bolsa de nicotina", "bolsas de nicotina", "zyn ", "velo ",
            ))
            if pouch_context:
                out["nicotine_mg_per_pouch"] = _num(m2.group(1))
                out["nicotine_source"] = "regex_pouch_mg"
            else:
                out["nicotine_mg_per_ml"] = _num(m2.group(1))
                out["nicotine_source"] = "regex_mg"

    tl = text.lower()
    nic_ctx = ("nicotin" in tl or "nic salt" in tl or "sal de nic" in tl
               or tl.startswith("nic ") or " nic " in tl
               or str(product_type or "").startswith("vape"))
    p = _PCT.search(text)
    if p and nic_ctx:
        out["nicotine_pct"] = _num(p.group(1))
        out["nicotine_source"] = out["nicotine_source"] or "regex_pct"

    out["puff_count"] = _puff_from_text(text, product_type)
    return out
