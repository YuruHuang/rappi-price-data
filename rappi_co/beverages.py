"""Reproducible beverage discovery, conservative enrichment, and audited exports.

Run ``python -m rappi_co.beverages --all-countries --dry-run`` before collecting.
The tobacco pipeline and its published workbooks are intentionally independent.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

import yaml

from rappi_co.collect.search import run as run_search
from rappi_co.configs import load_study_profile
from rappi_co.parsers.search_api import STUDY_SEARCH_PATH
from rappi_co.study import (COUNTRIES, ROOT, STUDY_CONFIG, _complete_source,
                            _file_record, _run_token, _write_json_atomic)

CONFIG = ROOT / "config" / "beverages.yml"
KEYS = ("country_code", "zone_slug", "store_id", "product_id")
MEASURES = ("volume_per_unit_ml", "pack_count", "total_volume_ml",
            "sugar_g_per_100ml", "sugar_g_per_serving", "serving_volume_ml", "abv_pct")
DETAIL_FIELDS = ("product_information", "ingredients_text", "nutrition_text", "detail_status",
                 "detail_url", "detail_retrieved_at", "detail_evidence_path", "detail_locale",
                 "detail_identity_method", "detail_scope", "detail_method", "detail_note", "detail_evidence_sha256")
INCLUDED = {"water", "ssb", "alcohol"}
SSB_CANDIDATE_FAMILIES = {"soft_drink", "energy_drink", "sports_drink", "juice",
                          "tea_coffee", "flavored_water", "dairy_beverage", "other_beverage"}
BASE_COLUMNS = [*KEYS, "country", "city", "currency", "address", "district", "latitude",
                "longitude", "store_name", "store_type", "master_product_id", "source_product_id",
                "ean", "name", "brand", "menu_section", "menu_subsection", "short_description", "price_local",
                "original_price_local", "availability", "scrape_timestamp", "source_terms",
                "alcoholic_beverage", "age_restriction", "restriction_tag",
                "source_url", "product_url", "store_url", "browser_url", "thumbnail_url", "attributes_json",
                "pack_format_raw", "quantity", "unit_type", "source_conflicts_json",
                "beverage_category", "beverage_subcategory", "classification_reason", "sugar_status", "ssb_candidate_status",
                *MEASURES, "price_per_liter_local", "beverage_flags", *DETAIL_FIELDS]


def plan_country(country: str, addresses: list[str] | None = None,
                 terms: list[str] | None = None) -> dict:
    profile = load_study_profile(country, STUDY_CONFIG)
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    if set(config["categories"]) != INCLUDED:
        raise ValueError("beverage categories must be water, ssb, alcohol")
    groups = [*config["categories"].values(), config["regional_terms"][country],
              *config["brand_queries"][country].values()]
    if any(not isinstance(g, list) or not g or
           any(not isinstance(q, str) or not q.strip() for q in g) for g in groups):
        raise ValueError("beverage query groups must contain nonempty text")
    expected = list(dict.fromkeys(q.strip() for group in groups for q in group))
    queries = expected if terms is None else list(dict.fromkeys(t.strip() for t in terms if t.strip()))
    if not queries:
        raise ValueError("at least one search term is required")
    zones = {z["slug"]: z for z in profile["zones"]}
    slugs = list(zones) if addresses is None else addresses
    if not slugs or len(set(slugs)) != len(slugs) or set(slugs) - set(zones):
        raise ValueError(f"invalid or duplicate {country} location: {slugs}")
    complete = set(slugs) == set(zones) and queries == expected
    return {
        "country_code": country, "country": profile["name"], "city": profile["city"],
        "currency": profile["currency"], "addresses": [zones[s] for s in slugs],
        "queries": queries, "requests": len(slugs) * len(queries),
        "protocol_status": "full" if complete else "partial", "full_protocol": complete,
        "scope": "beverages", "config_version": config["version"],
        "search_url": f"{profile['services_url'].rstrip('/')}{STUDY_SEARCH_PATH}",
        "catalog_completeness": "unknown; search results may be capped",
    }


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _key(row: dict) -> tuple[str, ...]:
    key = tuple(str(row.get(k) or "").strip() for k in KEYS)
    if not all(key):
        raise ValueError(f"observation identity requires {KEYS}: {key}")
    return key


def overlay_details(rows: list[dict], details: list[dict]) -> list[dict]:
    """Join only verified store/location observations; never join by name or master ID."""
    from rappi_co.collect.product_details import verify_observation_evidence

    output = [dict(row) for row in rows]
    index = {_key(row): row for row in output}
    if len(index) != len(rows):
        raise ValueError("duplicate observation keys")
    keys = [_key(detail) for detail in details]
    if len(set(keys)) != len(keys) or any(key not in index for key in keys):
        raise ValueError("duplicate or unmatched product detail key")
    for detail in details:
        key = _key(detail)
        target = index[key]
        status = str(detail.get("detail_status", ""))
        # Failure metadata is retained, but cannot inject unverified facts.
        for field in DETAIL_FIELDS:
            target[field] = detail.get(field, "")
        if status != "ok":
            for field in ("product_information", "ingredients_text", "nutrition_text"):
                target[field] = ""
        elif not all(detail.get(k) for k in
                     ("detail_identity_method", "detail_url", "detail_retrieved_at", "detail_evidence_path",
                      "detail_evidence_sha256")):
            raise ValueError(f"successful details require identity and evidence metadata: {key}")
        elif detail.get("detail_scope") != "observation" or detail["detail_identity_method"] not in {
                "pdp_primary_ids_and_heading", "store_route_and_card_id_and_dialog_name"}:
            raise ValueError(f"successful details require verified store and location observation scope: {key}")
        else:
            path = Path(detail["detail_evidence_path"])
            try:
                if path.is_symlink():
                    raise ValueError("detail evidence must be a regular file, not a symlink")
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != detail["detail_evidence_sha256"]:
                    raise ValueError("detail evidence checksum mismatch")
                evidence = json.loads(data)
            except (OSError, ValueError) as error:
                raise ValueError(f"cannot verify detail evidence for {key}: {error}") from error
            if not isinstance(evidence, dict):
                raise ValueError("detail evidence must be a JSON object")
            replayed = verify_observation_evidence(evidence, index[key])
            compare = set(DETAIL_FIELDS) - {"detail_evidence_path", "detail_evidence_sha256"}
            if any(str(detail.get(field) or "") != str(replayed.get(field) or "") for field in compare):
                raise ValueError(f"detail CSV facts or metadata differ from its replayed evidence: {key}")
    return output


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _write_csv(path: Path, rows: list[dict], columns: list[str] | None = None) -> None:
    cols = columns or list(dict.fromkeys(k for row in rows for k in row)) or list(KEYS)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _csv_value(row.get(k)) for k in cols})


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        val = float(value)
        return val if math.isfinite(val) else None
    except (TypeError, ValueError):
        return None


def _enrich(rows: list[dict]) -> list[dict]:
    from rappi_co.enrich.beverage_fields import enrich_beverage

    output = []
    for row in rows:
        item = {**row, **enrich_beverage(row)}
        price, volume = _number(row.get("price_local")), _number(item.get("total_volume_ml"))
        item["price_per_liter_local"] = (
            round(price * 1000 / volume, 6)
            if price is not None and price > 0 and volume is not None and volume > 0 else None)
        output.append(item)
    return output


def coverage(rows: list[dict], stage: str) -> list[dict]:
    groups: dict[tuple, list] = {}
    for row in rows:
        key = (row["country_code"], row["zone_slug"], row["beverage_category"])
        groups.setdefault(key, []).append(row)
    return [{"stage": stage, "country_code": key[0], "zone_slug": key[1],
             "beverage_category": key[2], "observations": len(group),
             **{f"{m}_present": sum(_number(r.get(m)) is not None for r in group) for m in MEASURES},
             "description_present": sum(bool(r.get("product_information")) for r in group),
             "detail_attempted": sum(bool(r.get("detail_status")) for r in group),
             "detail_ok": sum(r.get("detail_status") == "ok" for r in group)}
            for key, group in sorted(groups.items())]


def paired_coverage(before: list[dict], after: list[dict]) -> list[dict]:
    """Keep the baseline cohort fixed even when descriptions change classification."""
    left, right = ({_key(r): r for r in group} for group in (before, after))
    if left.keys() != right.keys():
        raise ValueError("coverage comparison requires identical observation keys")
    groups = {}
    for key, row in left.items():
        cohort = (row["country_code"], row["zone_slug"], row["beverage_category"])
        groups.setdefault(cohort, []).append((row, right[key]))
    records = []
    for cohort, pairs in sorted(groups.items()):
        record = dict(zip(("country_code", "zone_slug", "baseline_category"), cohort))
        record.update(observations=len(pairs),
                      detail_attempted=sum(bool(b.get("detail_status")) for a, b in pairs),
                      detail_ok=sum(b.get("detail_status") == "ok" for a, b in pairs),
                      classification_changed=sum(a["beverage_category"] != b["beverage_category"] for a, b in pairs))
        for measure in MEASURES:
            presence = [(_number(a.get(measure)) is not None, _number(b.get(measure)) is not None)
                        for a, b in pairs]
            record.update({f"{measure}_before": sum(a for a, b in presence),
                           f"{measure}_after": sum(b for a, b in presence),
                           f"{measure}_gained": sum(not a and b for a, b in presence),
                           f"{measure}_lost": sum(a and not b for a, b in presence)})
        records.append(record)
    return records


def review_sample(rows: list[dict], per_group: int = 12) -> list[dict]:
    """Deterministic stratified audit sample: flagged cases plus ordinary cases.

    This is a review aid, not a representative estimate of classification error.
    Each location/category contributes up to per_group rows and keeps its keys.
    """
    groups = {}
    for row in rows:
        groups.setdefault((row["zone_slug"], row["beverage_category"]), []).append(row)
    output = []
    for key in sorted(groups):
        group = groups[key]
        ranked = sorted(group, key=lambda r: hashlib.sha256("|".join(_key(r)).encode()).hexdigest())
        flagged = [r for r in ranked if r.get("beverage_flags") or r.get("source_conflict")]
        selected = flagged[:per_group // 2]
        used = {_key(r) for r in selected}
        selected += [r for r in ranked if _key(r) not in used][:per_group - len(selected)]
        output.extend({**r, "reviewer_category": "", "reviewer_notes": ""} for r in selected)
    return output


def _validate_sources(plan: dict, sources: dict[str, Path], root: Path) -> dict:
    from rappi_co.study import (_complete_raw_archive, _csv_matches_manifest,
                                _manifest_member, _source_timestamp)

    slugs = {z["slug"] for z in plan["addresses"]}
    if set(sources) != slugs:
        raise ValueError("sources must match exactly the planned locations")
    inputs = {}
    for slug, path in sources.items():
        path = Path(path)
        timestamp = _source_timestamp(path)
        manifest_path = path.with_name(path.name.replace("search_items_", "search_manifest_")).with_suffix(".json")
        if path.is_symlink() or manifest_path.is_symlink():
            raise ValueError("source and completion manifest must not be symlinks")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        zone = next(z for z in plan["addresses"] if z["slug"] == slug)
        if (not isinstance(manifest, dict) or manifest.get("complete") is not True or manifest.get("country_code") != plan["country_code"]
                or manifest.get("address") != slug or manifest.get("currency") != plan["currency"]
                or manifest.get("queries") != plan["queries"]
                or manifest.get("search_url") != plan["search_url"]
                or manifest.get("latitude") != zone["lat"] or manifest.get("longitude") != zone["lng"]):
            raise ValueError(f"source manifest does not match the country/location/currency/query plan: {slug}")
        exact = _manifest_member(path.parent, manifest.get("items"), f"search_items_{timestamp}.csv")
        stores = _manifest_member(path.parent, manifest.get("stores"), f"search_stores_{timestamp}.csv")
        raw = _manifest_member(path.parent, manifest.get("raw_directory"), f"search_raw_{timestamp}")
        if (exact is None or exact != path.resolve() or stores is None or raw is None
                or not _csv_matches_manifest(exact, manifest.get("n_items"),
                    {"store_id", "product_id", "country_code", "currency", "scrape_timestamp"})
                or not _csv_matches_manifest(stores, manifest.get("n_stores"), {"store_id"})
                or not _complete_raw_archive(raw, manifest, plan["queries"])):
            raise ValueError(f"selected exact source archive is incomplete or aliased: {path}")
        item_rows, store_rows = _read_csv(exact), _read_csv(stores)
        if (any(row.get("country_code") != plan["country_code"] or row.get("currency") != plan["currency"]
                or row.get("scrape_timestamp") != timestamp for row in item_rows)
                or {r.get("store_id") for r in item_rows} != {r.get("store_id") for r in store_rows}
                or len({r.get("store_id") for r in store_rows}) != len(store_rows)):
            raise ValueError("source CSV country, currency, run time, or store identities disagree with its manifest")
        inputs[slug] = {"items": _file_record(path, root, rows=True),
                        "stores": _file_record(stores, root, rows=True),
                        "manifest": _file_record(manifest_path, root),
                        "raw_responses": [_file_record(raw / entry["raw_file"], root)
                                          for entry in manifest["term_results"]]}
    return inputs


def _unchanged(fingerprints: dict[Path, str], label: str) -> None:
    for path, expected in fingerprints.items():
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise RuntimeError(f"{label} input changed during export: {path}") from error
        if actual != expected:
            raise RuntimeError(f"{label} input changed during export: {path}")


def _excel_frame(frame, table: str, full_csv: str, truncations: list[dict]):
    """Make Excel's cell limit explicit while the CSV retains every character."""
    for column in frame.columns:
        for index, value in frame[column].items():
            if isinstance(value, str) and len(value) > 32767:
                record = {"sheet_name": table, "excel_row": int(index) + 2,
                          "column_name": column, "original_characters": len(value),
                          "full_value_source": full_csv}
                record.update({key: frame.at[index, key] for key in KEYS if key in frame.columns})
                truncations.append(record)
                frame.at[index, column] = value[:32000] + " [TRUNCATED IN XLSX; complete value in " + full_csv + "]"
    return frame


def export_country(plan: dict, sources: dict[str, Path], data_root: Path,
                   details_path: Path | None = None) -> dict:
    from rappi_co.parsers.beverage_search import replay_search
    from rappi_co.export.study_deliverable import _xlsx_safe_frame
    import pandas as pd

    input_records = _validate_sources(plan, sources, data_root)
    source_fingerprints = {}
    for group in input_records.values():
        for record in group.values():
            for member in record if isinstance(record, list) else [record]:
                source_fingerprints[(data_root / member["data_root_relative_path"]).resolve()] = member["sha256"]
    config_paths = sorted((ROOT / "config").rglob("*.yml"))
    config_fingerprints = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in config_paths}
    code_paths = sorted((ROOT / "rappi_co").rglob("*.py"))
    code_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths}
    detail_rows, detail_fingerprints = [], {}
    if details_path is not None:
        details_path = Path(details_path).resolve()
        detail_fingerprints[details_path] = hashlib.sha256(details_path.read_bytes()).hexdigest()
        detail_rows = _read_csv(details_path)
        for detail in detail_rows:
            if detail.get("detail_status") == "ok" and detail.get("detail_evidence_path"):
                evidence = Path(detail["detail_evidence_path"])
                if not evidence.is_absolute():
                    evidence = details_path.parent / evidence
                    detail["detail_evidence_path"] = str(evidence.resolve())
                if evidence.is_file():
                    detail_fingerprints[evidence.resolve()] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    token = _run_token()
    destination = data_root / plan["country_code"] / "processed" / token
    destination.mkdir(parents=True, exist_ok=False)
    incomplete = destination / "INCOMPLETE"
    incomplete.write_text("This export is incomplete until a complete beverage manifest is written.\n")
    raw, query_rows = [], []
    for zone in plan["addresses"]:
        parsed, diagnostics = replay_search(Path(sources[zone["slug"]]))
        for row in parsed:
            row.update({k: plan[k] for k in ("country_code", "country", "city", "currency")})
            row.update(zone_slug=zone["slug"], address=zone["address"], district=zone["district"],
                       latitude=zone["lat"], longitude=zone["lng"])
        raw.extend(parsed)
        query_rows.extend({**d, "country_code": plan["country_code"], "zone_slug": zone["slug"]}
                          for d in diagnostics)
    if len({_key(r) for r in raw}) != len(raw):
        raise ValueError("duplicate keys in replayed beverage observations")
    baseline = _enrich(raw)
    rows = baseline
    if details_path is not None:
        rows = _enrich(overlay_details(raw, detail_rows))
    for row in rows:
        if row.get("beverage_category") not in INCLUDED | {"non_ssb", "review", "excluded"}:
            raise ValueError("unknown beverage classification")
        if row["beverage_category"] in INCLUDED:
            price = _number(row.get("price_local"))
            if price is None or price <= 0:
                row["beverage_flags"] = [*row.get("beverage_flags", []), "missing_or_invalid_price"]

    items = [r for r in rows if r["beverage_category"] in INCLUDED]
    ssb_candidates = [{**r, "ssb_candidate_status": (
        "confirmed_sugar_sweetened" if r["beverage_category"] == "ssb" else "sweetening_unconfirmed")}
        for r in rows if r["beverage_category"] == "ssb" or (
            r["beverage_category"] == "review" and r["beverage_subcategory"] in SSB_CANDIDATE_FAMILIES)]
    review = [r for r in rows if r["beverage_category"] == "review"]
    comparison = [r for r in rows if r["beverage_category"] == "non_ssb"]
    candidates = [r for r in rows if r["beverage_category"] != "excluded"]
    by_store = {}
    for row in candidates:
        key = tuple(row[k] for k in ("country_code", "zone_slug", "store_id"))
        st = by_store.setdefault(key, {**{k: row.get(k) for k in
                                     ("country_code", "zone_slug", "store_id", "store_name", "store_type")},
                                      "candidate_observations": 0, "included_observations": 0})
        st["candidate_observations"] += 1
        st["included_observations"] += row["beverage_category"] in INCLUDED
    stores = list(by_store.values())
    locations = [{"country_code": plan["country_code"], "currency": plan["currency"], **zone}
                 for zone in plan["addresses"]]
    cov = coverage(baseline, "search_only")
    if details_path is not None:
        cov += coverage(rows, "with_product_information")
    summary = [{"metric": k, "value": v} for k, v in {
        "country_code": plan["country_code"], "currency": plan["currency"],
        "protocol_status": plan["protocol_status"], "raw_observations": len(rows),
        "included_observations": len(items), "review_observations": len(review),
        "ssb_candidate_observations": len(ssb_candidates),
        "comparison_observations": len(comparison), "excluded_observations": len(rows) - len(candidates),
        "catalog_completeness": plan["catalog_completeness"],
        **{f"products_{cat}": sum(r["beverage_category"] == cat for r in rows) for cat in sorted(INCLUDED)},
    }.items()]
    # Keep the analyst tables focused on validated beverage quantities. Legacy
    # parser guesses (volume_ml, COP unit prices, etc.) remain in the raw audit.
    columns = list(dict.fromkeys([*BASE_COLUMNS,
                                *(f"{m}_{suffix}" for m in MEASURES for suffix in ("source", "evidence")),
                                "source_conflict", "source_evidence_paths", "source_manifest_path",
                                "beverage_evidence_json"]))
    audit_columns = list(dict.fromkeys([*columns, *(k for r in rows for k in r)]))
    tables = {"items": items, "ssb_candidates": ssb_candidates, "review": review, "comparison": comparison, "audit": rows,
              "candidates": candidates, "stores": stores, "locations": locations,
              "coverage": cov, "query_yield": query_rows, "summary": summary,
              "review_sample": review_sample(rows)}
    if details_path is not None:
        tables["detail_comparison"] = paired_coverage(baseline, rows)
    artifacts = {}
    for name, values in tables.items():
        path = destination / f"beverage_{name}_{token}.csv"
        table_columns = audit_columns if name == "audit" else (
            columns if name in {"items", "ssb_candidates", "review", "comparison", "candidates"} else None)
        if name == "review_sample":
            table_columns = [*columns, "reviewer_category", "reviewer_notes"]
        _write_csv(path, values, table_columns)
        artifacts[f"{name}_csv"] = path
    dictionary = [{"column": col, "definition": definition(col)} for col in columns]
    book = destination / f"beverages_{plan['country_code']}_{token}.xlsx"
    # Large raw JSON is retained intact in CSV; Excel cannot hold >32767 chars/cell.
    excel_columns = [c for c in columns if c not in {"source_product_json", "beverage_evidence_json"}]
    truncations = []
    with pd.ExcelWriter(book, engine="openpyxl") as writer:
        sheet_names = ["summary", "items", "ssb_candidates", "review", "comparison", "stores", "locations", "coverage", "query_yield"]
        if details_path is not None:
            sheet_names.append("detail_comparison")
        for name in sheet_names:
            frame = pd.DataFrame(tables[name], columns=(excel_columns if name in
                                 {"items", "ssb_candidates", "review", "comparison"} else None))
            frame = frame.apply(lambda column: column.map(_csv_value))
            frame = _excel_frame(frame, name, artifacts[f"{name}_csv"].name, truncations)
            _xlsx_safe_frame(frame).to_excel(writer, sheet_name=name, index=False)
        truncation_columns = ["sheet_name", "excel_row", "column_name", "original_characters", "full_value_source", *KEYS]
        if truncations:
            pd.DataFrame(truncations, columns=truncation_columns).to_excel(writer, sheet_name="excel_truncations", index=False)
        pd.DataFrame(dictionary).to_excel(writer, sheet_name="data_dictionary", index=False)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cells in sheet.columns:
                sheet.column_dimensions[cells[0].column_letter].width = min(55, max(14, len(str(cells[0].value)) + 2))
    artifacts["xlsx"] = book
    truncation_path = destination / f"beverage_excel_truncations_{token}.csv"
    _write_csv(truncation_path, truncations, truncation_columns)
    artifacts["excel_truncations_csv"] = truncation_path
    tables["excel_truncations"] = truncations
    _unchanged(source_fingerprints, "source")
    _unchanged(config_fingerprints, "configuration")
    _unchanged(detail_fingerprints, "detail evidence")
    if code_hashes != {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths}:
        raise RuntimeError("pipeline code changed during export; rebuild after edits finish")
    manifest = {
        "schema_version": 1, "complete": True, "run_id": token, "plan": plan,
        "inputs": input_records, "config_sha256": config_fingerprints[CONFIG],
        "config_files_sha256": {str(p.relative_to(ROOT)): digest for p, digest in config_fingerprints.items()},
        "code_sha256": code_hashes,
        "runtime": {"python": sys.version.split()[0], "pandas": pd.__version__, "pyyaml": yaml.__version__},
        "outputs": {k: _file_record(p, data_root, rows=k.endswith("_csv")) for k, p in artifacts.items()},
        "counts": {name: len(values) for name, values in tables.items()},
        "detail_input": ({"path": str(details_path.resolve()),
                          "sha256": detail_fingerprints[details_path],
                          "evidence": [{"path": str(p), "sha256": digest} for p, digest in detail_fingerprints.items()
                                       if p != details_path]}
                         if details_path else None),
    }
    manifest_path = destination / f"beverage_manifest_{token}.json"
    _write_json_atomic(manifest_path, manifest)
    incomplete.unlink()
    return {"manifest": str(manifest_path), "counts": manifest["counts"],
            **{k: str(p) for k, p in artifacts.items()}}


def definition(column: str) -> str:
    special = {
        "beverage_category": "water, ssb, alcohol, non_ssb comparison, review, or excluded; ssb requires sweetening evidence",
        "beverage_subcategory": "Rule-based drink family; review juice/dairy scope before pooling",
        "classification_reason": "Auditable reason for the assigned class; not a probability",
        "sugar_status": "Sugar-sweetening evidence/claim, distinct from a measured nutrient concentration",
        "ssb_candidate_status": "SSB candidate sheet only: confirmed_sugar_sweetened or sweetening_unconfirmed; candidate inclusion does not establish an SSB",
        "volume_per_unit_ml": "Explicit volume per container, in milliliters",
        "pack_count": "Explicit number of containers; blank if unknown or ambiguous",
        "total_volume_ml": "Explicit or coherently derived volume in the entire sale unit, in milliliters",
        "sugar_g_per_100ml": "Total sugars g/100 ml with explicit basis, or derived from explicit serving size; blank is not zero",
        "sugar_g_per_serving": "Total sugars g per explicitly identified serving",
        "serving_volume_ml": "Nutrition serving size in ml; not package volume",
        "abv_pct": "Alcohol by volume percent supported by explicit evidence; no brand imputation",
        "price_per_liter_local": "price_local / total_volume_ml * 1000; blank without a valid denominator",
        "beverage_flags": "Quality and scope warnings; unresolved conflicts retain blank normalized values",
        "availability": "Explicit source availability; unknown when no source signal is supplied",
        "price_local": "Observed sale price, in the currency column; source anomalies are flagged",
        "original_price_local": "Observed original price in local currency; blank when unavailable",
        "short_description": "Untruncated description supplied in search JSON, if present",
        "product_information": "Exact product information from a verified product/store detail observation",
        "attributes_json": "Original structured source attributes, preserved as JSON",
        "source_product_json": "Full first-seen raw product object; available in CSV audit",
        "source_conflicts_json": "Differences across duplicate query sightings; source retained for review",
        "source_terms": "All search queries that returned this store-product observation",
        "detail_status": "Outcome of optional product-information collection; blank when not attempted",
        "capped_store_groups": "Historical diagnostic: store groups with at least 25 rows; not an established platform limit or proof of saturation",
        "beverage_evidence_json": "All extracted candidate evidence, including conflicts; full content in CSV audit",
    }
    if column in special:
        return special[column]
    if column.endswith("_source"):
        return "Source field(s) supporting " + column.removesuffix("_source")
    if column.endswith("_evidence"):
        return "Exact supporting text for " + column.removesuffix("_evidence")
    if column in KEYS:
        return "Observation identity component; preserve as text: " + column
    return "Source or provenance field: " + column


def run_country(country: str, addresses=None, terms=None, *, skip_collect=False,
                collect_only=False, data_root: Path | None = None, min_delay=1.0,
                max_delay=3.0, details_path: Path | None = None) -> dict:
    root = Path(data_root) if data_root is not None else ROOT / "data" / "beverages"
    plan = plan_country(country, addresses, terms)
    sources = {}
    for zone in plan["addresses"]:
        slug = zone["slug"]
        directory = root / country / "raw" / slug
        if skip_collect:
            source = _complete_source(directory, country, slug, plan["queries"])
        else:
            source, _ = run_search(slug, plan["queries"], directory, country=country,
                                   min_delay=min_delay, max_delay=max_delay)
        sources[slug] = source
    result = {"plan": plan, "sources": {s: str(p) for s, p in sources.items()}}
    if not collect_only:
        result["deliverable"] = export_country(plan, sources, root, details_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--country", choices=COUNTRIES, action="append")
    group.add_argument("--all-countries", action="store_true")
    parser.add_argument("--address", action="append")
    parser.add_argument("--terms", help="comma-separated partial-protocol query override")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-collect", action="store_true")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--data-root", type=Path, default=ROOT / "data" / "beverages")
    parser.add_argument("--details", type=Path, help="verified detail CSV, single-country rebuild only")
    parser.add_argument("--min-delay", type=float, default=1.0)
    parser.add_argument("--max-delay", type=float, default=3.0)
    args = parser.parse_args()
    countries = list(COUNTRIES) if args.all_countries else args.country
    if len(set(countries)) != len(countries):
        parser.error("duplicate countries are not allowed")
    if args.address and len(countries) != 1:
        parser.error("--address requires one country")
    if args.skip_collect and args.collect_only:
        parser.error("--skip-collect and --collect-only cannot be combined")
    if args.details and (len(countries) != 1 or not args.skip_collect or args.collect_only):
        parser.error("--details requires one country and --skip-collect")
    terms = None if args.terms is None else args.terms.split(",")
    result = []
    for code in countries:
        if args.dry_run:
            result.append(plan_country(code, args.address, terms))
        else:
            result.append(run_country(code, args.address, terms, skip_collect=args.skip_collect,
                                     collect_only=args.collect_only, data_root=args.data_root,
                                     min_delay=args.min_delay, max_delay=args.max_delay,
                                     details_path=args.details))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
