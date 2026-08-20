"""Best-effort ABV / sugar extraction from product name + short description."""
from __future__ import annotations

import re
from typing import Optional, Tuple

_ABV_MIN, _ABV_MAX = 0.0, 60.0
_SUGAR_MIN, _SUGAR_MAX = 0.0, 200.0

_ABV_PATTERNS = [
    re.compile(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:vol|alc(?:ohol)?)", re.IGNORECASE),
    re.compile(r"\balc(?:ohol)?\s*[: ]?\s*(\d+(?:[.,]\d+)?)\s*%", re.IGNORECASE),
    re.compile(r"\bgrad[oa]s?\s*alc(?:oh[oó]lic[oa]s?)?\s*[: ]?\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE),
    re.compile(r"(\d+(?:[.,]\d+)?)\s*°\s*(?:gl|alc)?", re.IGNORECASE),
]

_SUGAR_PATTERNS = [
    re.compile(r"(\d+(?:[.,]\d+)?)\s*g\s*(?:de\s*)?az[uú]car", re.IGNORECASE),
    re.compile(r"az[uú]car(?:es)?\s*(?:a[ñn]adid[ao]s?)?\s*[: ]?\s*(\d+(?:[.,]\d+)?)\s*g", re.IGNORECASE),
    re.compile(r"(\d+(?:[.,]\d+)?)\s*g\s*/\s*100\s*ml", re.IGNORECASE),
]


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", "."))
    except (TypeError, ValueError):
        return None


def extract_abv(text: str) -> Tuple[Optional[float], Optional[str]]:
    if not text:
        return None, None
    for pat in _ABV_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        val = _to_float(m.group(1))
        if val is None:
            continue
        if not (_ABV_MIN <= val <= _ABV_MAX):
            continue
        return val, m.group(0).strip()
    return None, None


def extract_sugar(text: str) -> Tuple[Optional[float], Optional[str]]:
    if not text:
        return None, None
    for pat in _SUGAR_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        val = _to_float(m.group(1))
        if val is None:
            continue
        if not (_SUGAR_MIN <= val <= _SUGAR_MAX):
            continue
        return val, m.group(0).strip()
    return None, None


def enrich_item(item: dict) -> dict:
    text = " ".join(filter(None, [
        item.get("name") or "",
        item.get("short_description") or "",
        item.get("brand") or "",
    ]))
    abv, abv_ev = extract_abv(text)
    sug, sug_ev = extract_sugar(text)
    item["abv_pct_from_text"] = abv
    item["abv_evidence"] = abv_ev
    item["sugar_g_from_text"] = sug
    item["sugar_evidence"] = sug_ev
    return item
