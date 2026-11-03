"""Read user-supplied delivery points without geocoding or network requests.

Files may contain any positive number of locations. Coordinates must already be
verified by the researcher. This module validates the whole file before applying
an optional country filter so a bad row cannot disappear behind that filter.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata


COUNTRY_CODES = frozenset({"ar", "co", "pe", "mx"})
ALIASES = {
    "country_code": ("country_code", "country"),
    "slug": ("slug", "location_id"),
    "lat": ("lat", "latitude"),
    "lng": ("lng", "longitude", "lon"),
    "address": ("address", "full_address"),
    "district": ("district",),
    "city": ("city",),
}


class LocationError(ValueError):
    """A supplied location file is missing, malformed, or ambiguous."""


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _header(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LocationError("column names must be nonempty text")
    return re.sub(r"\s+", "_", value.strip().lstrip("\ufeff").lower())


def _mapping(record: dict, row: int) -> dict:
    normalized = {}
    for key, value in record.items():
        name = _header(key)
        if name in normalized:
            raise LocationError(f"row {row}: duplicate column {name!r}")
        normalized[name] = value
    return normalized


def _country(value, label: str) -> str:
    if not isinstance(value, str):
        raise LocationError(f"{label}: country must be one of ar, co, pe, mx")
    code = value.strip().lower()
    if code not in COUNTRY_CODES:
        raise LocationError(f"{label}: unsupported country {value!r}; use ar, co, pe, mx")
    return code


def _coordinate(value, field: str, label: str) -> float:
    if isinstance(value, bool) or _blank(value):
        raise LocationError(f"{label}: {field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise LocationError(f"{label}: {field} must be a finite number") from error
    bound = 90 if field == "lat" else 180
    if not math.isfinite(number) or not -bound <= number <= bound:
        raise LocationError(f"{label}: {field} must be finite and between {-bound} and {bound}")
    return number


def _value(record: dict, field: str, label: str):
    values = [record[name] for name in ALIASES[field]
              if name in record and not _blank(record[name])]
    if not values:
        return None
    if field in {"lat", "lng"}:
        values = [_coordinate(value, field, label) for value in values]
    elif field == "country_code":
        values = [_country(value, label) for value in values]
    else:
        if any(not isinstance(value, str) for value in values):
            # Numeric IDs are common in spreadsheet exports, but address fields
            # should not silently accept a date, Boolean, or arbitrary object.
            if field == "slug" and all(isinstance(v, (str, int)) and not isinstance(v, bool)
                                        for v in values):
                values = [str(value) for value in values]
            else:
                raise LocationError(f"{label}: {field} must be text")
        values = [value.strip() for value in values]
    if any(value != values[0] for value in values[1:]):
        raise LocationError(f"{label}: conflicting aliases for {field}")
    return values[0]


def _generated_slug(address: str, lat: float, lng: float) -> str:
    canonical = " ".join(address.casefold().split())
    ascii_address = unicodedata.normalize("NFKD", canonical).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^a-z0-9]+", "-", ascii_address).strip("-")[:48].rstrip("-")
    identity = json.dumps([canonical, lat, lng], ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"{stem or 'location'}-{digest}"


def _structured_records(payload) -> list:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise LocationError("expected a list or a mapping containing 'zones' or 'locations'")
    keys = [key for key in ("zones", "locations") if key in payload]
    if len(keys) != 1 or not isinstance(payload[keys[0]], list):
        raise LocationError("provide exactly one list named 'zones' or 'locations'")
    defaults = {key: payload[key] for key in ("country", "country_code") if key in payload}
    records = []
    for record in payload[keys[0]]:
        # Preserve top-level country metadata from existing study YAML profiles.
        records.append({**defaults, **record} if isinstance(record, dict) else record)
    return records


def _tabular_records(rows) -> list[dict]:
    iterator = iter(rows)
    try:
        raw_headers = next(iterator)
    except StopIteration:
        return []
    headers = [_header(value) for value in raw_headers]
    if len(headers) != len(set(headers)):
        raise LocationError("duplicate column names")
    records = []
    for number, values in enumerate(iterator, start=2):
        if all(_blank(value) for value in values):
            continue
        if len(values) > len(headers) and any(not _blank(v) for v in values[len(headers):]):
            raise LocationError(f"row {number}: more values than column names")
        padded = list(values[:len(headers)]) + [None] * max(0, len(headers) - len(values))
        records.append(dict(zip(headers, padded)))
    return records


def _read_records(path: Path) -> list:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return _tabular_records(csv.reader(handle, delimiter="\t" if suffix == ".tsv" else ","))
    if suffix in {".json", ".yaml", ".yml"}:
        with path.open(encoding="utf-8-sig") as handle:
            if suffix == ".json":
                payload = json.load(handle)
            else:
                import yaml
                payload = yaml.safe_load(handle)
        return _structured_records(payload)
    if suffix == ".xlsx":
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            return _tabular_records(book.worksheets[0].iter_rows(values_only=True))
        finally:
            book.close()
    raise LocationError("supported location formats are CSV, TSV, JSON, YAML, YML, and XLSX")


def load_location_file(path: str | Path, country: str | None = None) -> list[dict]:
    """Return normalized delivery points, optionally restricted to one country.

    Untagged rows are retained for a single-country caller. Tagged rows for other
    countries are validated but filtered out. A caller spanning several countries
    must reject untagged rows rather than interpreting them repeatedly. An empty
    result after filtering is allowed; an entirely empty input file is an error.
    District defaults to an empty string. City and country_code are optional.
    """
    selected = _country(country, "country filter") if country is not None else None
    source = Path(path)
    try:
        records = _read_records(source)
    except LocationError as error:
        raise LocationError(f"{source.name}: {error}") from error
    except (OSError, ValueError, csv.Error) as error:
        raise LocationError(f"cannot read location file {source}: {error}") from error
    # YAML and XLSX libraries have parser exceptions outside ValueError.
    except Exception as error:
        raise LocationError(f"cannot parse location file {source}: {error}") from error
    normalized = []
    seen = set()
    for number, raw in enumerate(records, start=1):
        label = f"{source.name} row {number}"
        if not isinstance(raw, dict):
            raise LocationError(f"{label}: location must be a mapping")
        if all(_blank(value) for value in raw.values()):
            continue
        record = _mapping(raw, number)
        code = _value(record, "country_code", label)
        address = _value(record, "address", label)
        lat = _value(record, "lat", label)
        lng = _value(record, "lng", label)
        if not address or lat is None or lng is None:
            raise LocationError(f"{label}: address and numeric lat/lng are required; no geocoding is performed")
        slug = _value(record, "slug", label) or _generated_slug(address, lat, lng)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", slug):
            raise LocationError(f"{label}: slug must start with a letter or number and contain only letters, numbers, '_' or '-'")
        identity = (code, slug)
        if identity in seen:
            raise LocationError(f"{label}: duplicate location slug {slug!r} for {code or 'untagged country'}")
        seen.add(identity)
        location = {"slug": slug, "lat": lat, "lng": lng, "address": address,
                    "district": _value(record, "district", label) or ""}
        city = _value(record, "city", label)
        if city:
            location["city"] = city
        if code:
            location["country_code"] = code
        normalized.append(location)
    if not normalized:
        raise LocationError(f"{source.name}: location file must contain at least one location")
    result = [row for row in normalized
              if selected is None or not row.get("country_code") or row["country_code"] == selected]
    # An untagged row and a tagged row can resolve to the same country after the
    # caller supplies its country. Reject that collision before any collection.
    if selected is not None:
        selected_slugs = [row["slug"] for row in result]
        if len(selected_slugs) != len(set(selected_slugs)):
            raise LocationError(f"{source.name}: duplicate location slug after selecting country {selected}")
    return result


def location_file_record(path: str | Path) -> dict:
    """Record the exact custom input file used to plan a collection."""
    source = Path(path).resolve()
    try:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError as error:
        raise LocationError(f"cannot read location file {source}: {error}") from error
    return {"path": str(source), "sha256": digest}


def validate_location_scope(path: str | Path, countries) -> None:
    """Require unambiguous coverage of every requested country before running."""
    requested = [_country(code, "country selection") for code in countries]
    if not requested or len(requested) != len(set(requested)):
        raise LocationError("select at least one country without duplicate country codes")
    rows = load_location_file(path)
    if len(requested) > 1 and any(not row.get("country_code") for row in rows):
        raise LocationError("multi-country location files require country_code for every location")
    for code in requested:
        # Reapply the public filter to detect slug collisions between tagged and
        # untagged points when a single country is selected.
        if not load_location_file(path, code):
            raise LocationError(f"location file has no delivery points for requested country {code}")
