"""Validated loaders for the YAML configs.

Malformed configs should fail loud here, not surface as a cryptic KeyError deep
inside a multi-hour crawl.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml


STUDY_CATEGORIES = (
    "nicotine_pouches",
    "electronic_cigarettes",
    "heated_tobacco",
    "cigarettes",
)
MARKET_SCOPES = {"international", "local_market"}
MATCH_MODES = {"distinctive", "context_required"}


class ConfigError(ValueError):
    """A config file is missing required keys or holds invalid values."""


def _load_mapping(path: Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{p.name}: expected a YAML mapping, got {type(data).__name__}")
    return data


def load_zones(path: Path) -> list[dict]:
    """Return the validated ``zones`` list from a zones_*.yml file."""
    name = Path(path).name
    zones = _load_mapping(path).get("zones")
    if not isinstance(zones, list) or not zones:
        raise ConfigError(f"{name}: 'zones' must be a non-empty list")
    seen_slugs: set[str] = set()
    for i, z in enumerate(zones):
        if not isinstance(z, dict):
            raise ConfigError(f"{name}: zone #{i} must be a mapping")
        if not z.get("slug"):
            raise ConfigError(f"{name}: zone #{i} is missing 'slug'")
        if str(z["slug"]) in seen_slugs:
            raise ConfigError(f"{name}: duplicate zone slug '{z['slug']}'")
        seen_slugs.add(str(z["slug"]))
        try:
            lat, lng = float(z["lat"]), float(z["lng"])
        except (KeyError, TypeError, ValueError):
            raise ConfigError(f"{name}: zone '{z.get('slug')}' needs numeric 'lat'/'lng'")
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ConfigError(f"{name}: zone '{z['slug']}' lat/lng out of range ({lat}, {lng})")
    return zones


def load_seed_paths(path: Path) -> list[dict]:
    """Return the validated ``seed_paths`` list from a seed_paths_*.yml file."""
    name = Path(path).name
    seeds = _load_mapping(path).get("seed_paths")
    if not isinstance(seeds, list) or not seeds:
        raise ConfigError(f"{name}: 'seed_paths' must be a non-empty list")
    for i, s in enumerate(seeds):
        if not isinstance(s, dict) or not s.get("path") or not s.get("store_type"):
            raise ConfigError(f"{name}: seed #{i} needs both 'path' and 'store_type'")
        if not str(s["path"]).startswith("/"):
            raise ConfigError(f"{name}: seed '{s['path']}' path must start with '/'")
    return seeds


def load_country_profiles(path: Path) -> dict[str, dict]:
    """Return validated country metadata from countries.yml."""
    name = Path(path).name
    countries = _load_mapping(path).get("countries")
    if not isinstance(countries, dict) or not countries:
        raise ConfigError(f"{name}: 'countries' must be a non-empty mapping")
    for code, profile in countries.items():
        if not isinstance(code, str) or len(code) != 2 or code != code.lower():
            raise ConfigError(f"{name}: country codes must be two lowercase letters")
        required = ("name", "city", "currency", "locale", "timezone", "rappi_base_url",
                    "services_url", "bounds")
        if not isinstance(profile, dict) or any(not profile.get(k) for k in required):
            raise ConfigError(f"{name}: country '{code}' needs {', '.join(required)}")
        if len(str(profile["currency"])) != 3 or str(profile["currency"]) != str(profile["currency"]).upper():
            raise ConfigError(f"{name}: country '{code}' needs a three-letter uppercase currency")
        for key in ("rappi_base_url", "services_url"):
            parsed = urlparse(str(profile[key]))
            if parsed.scheme != "https" or not parsed.netloc:
                raise ConfigError(f"{name}: country '{code}' needs an https {key}")
        bounds = profile["bounds"]
        if not isinstance(bounds, dict):
            raise ConfigError(f"{name}: country '{code}' bounds must be a mapping")
        for axis in ("lat", "lng"):
            pair = bounds.get(axis)
            if (not isinstance(pair, list) or len(pair) != 2
                    or not all(isinstance(v, (int, float)) for v in pair)
                    or pair[0] >= pair[1]):
                raise ConfigError(f"{name}: country '{code}' bounds.{axis} needs [min, max]")
    return countries


def load_study_terms(path: Path) -> dict[str, list[str]]:
    """Return the fixed generic queries, grouped by product category."""
    name = Path(path).name
    categories = _load_mapping(path).get("categories")
    if not isinstance(categories, dict) or set(categories) != set(STUDY_CATEGORIES):
        raise ConfigError(f"{name}: categories must be exactly {list(STUDY_CATEGORIES)}")
    seen: set[str] = set()
    for category in STUDY_CATEGORIES:
        terms = categories[category]
        if not isinstance(terms, list) or not terms:
            raise ConfigError(f"{name}: '{category}' must have at least one query")
        for i, term in enumerate(terms):
            if not isinstance(term, str) or not term.strip():
                raise ConfigError(f"{name}: {category} query #{i} must be non-empty text")
            normalized = " ".join(term.casefold().split())
            if normalized in seen:
                raise ConfigError(f"{name}: duplicate query '{term}'")
            seen.add(normalized)
    return categories


def load_brand_terms(path: Path) -> list[dict]:
    """Return validated brand queries from a brand_terms_*.yml file."""
    name = Path(path).name
    grouped = _load_mapping(path).get("brand_terms")
    if not isinstance(grouped, dict) or set(grouped) != set(STUDY_CATEGORIES):
        raise ConfigError(f"{name}: brand_terms must contain exactly {list(STUDY_CATEGORIES)}")
    rows: list[dict] = []
    seen_queries: set[str] = set()
    for category in STUDY_CATEGORIES:
        entries = grouped[category]
        if not isinstance(entries, list):
            raise ConfigError(f"{name}: '{category}' brand terms must be a list")
        if len(entries) > 10:
            raise ConfigError(f"{name}: '{category}' has {len(entries)} brands; maximum is 10")
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ConfigError(f"{name}: {category} brand #{i} must be a mapping")
            required = ("brand", "query", "market_scope", "match")
            if any(not entry.get(k) for k in required):
                raise ConfigError(f"{name}: {category} brand #{i} needs {', '.join(required)}")
            if entry["market_scope"] not in MARKET_SCOPES:
                raise ConfigError(f"{name}: {entry['brand']} has invalid market_scope")
            if entry["match"] not in MATCH_MODES:
                raise ConfigError(f"{name}: {entry['brand']} has invalid match mode")
            aliases = entry.get("aliases", [])
            if (not isinstance(aliases, list)
                    or any(not isinstance(alias, str) or not alias.strip() for alias in aliases)):
                raise ConfigError(f"{name}: {entry['brand']} aliases must be a list of text")
            normalized = " ".join(str(entry["query"]).casefold().split())
            if normalized in seen_queries:
                raise ConfigError(f"{name}: duplicate brand query '{entry['query']}'")
            seen_queries.add(normalized)
            rows.append({"category": category, **entry})
    return rows


def brand_variants(entry: dict) -> list[str]:
    """Return configured and common compact spellings for one brand."""
    brand = str(entry["brand"]).strip()
    variants = [brand, *(str(alias).strip() for alias in entry.get("aliases", []))]
    compact = re.sub(r"[\s&+./_-]+", "", brand)
    if len(compact) >= 6:
        variants.append(compact)
    return list(dict.fromkeys(value.casefold() for value in variants if value))


def load_study_profile(country: str, config_dir: Path) -> dict:
    """Load one complete multicountry collection profile."""
    code = str(country).strip().lower()
    config_dir = Path(config_dir)
    countries = load_country_profiles(config_dir / "countries.yml")
    if code not in countries:
        raise ConfigError(f"unsupported country {country!r}; expected one of {sorted(countries)}")
    profile = {"country_code": code, **countries[code]}
    zones_path = config_dir / f"zones_{code}.yml"
    if _load_mapping(zones_path).get("country") != code:
        raise ConfigError(f"{zones_path.name}: country must be '{code}'")
    zones = load_zones(zones_path)
    if len(zones) != 2:
        raise ConfigError(f"{zones_path.name}: collection profiles require exactly two zones")
    lat_bounds, lng_bounds = profile["bounds"]["lat"], profile["bounds"]["lng"]
    for zone in zones:
        if not zone.get("address") or not zone.get("district"):
            raise ConfigError(f"{zones_path.name}: zone '{zone['slug']}' needs address and district")
        lat, lng = float(zone["lat"]), float(zone["lng"])
        if not (lat_bounds[0] <= lat <= lat_bounds[1]
                and lng_bounds[0] <= lng <= lng_bounds[1]):
            raise ConfigError(f"{zones_path.name}: zone '{zone['slug']}' is outside {profile['city']}")
    terms = load_study_terms(config_dir / "terms.yml")
    brands_path = config_dir / f"brand_terms_{code}.yml"
    if _load_mapping(brands_path).get("country") != code:
        raise ConfigError(f"{brands_path.name}: country must be '{code}'")
    brands = load_brand_terms(brands_path)
    return {**profile, "zones": zones, "generic_terms": terms, "brand_terms": brands}


def study_queries(profile: dict) -> list[str]:
    """Return generic then brand-qualified queries, de-duplicated in file order."""
    queries = [term for category in STUDY_CATEGORIES
               for term in profile["generic_terms"][category]]
    queries.extend(entry["query"] for entry in profile["brand_terms"])
    return list(dict.fromkeys(q.strip() for q in queries if q and q.strip()))
