"""Audit geographic scope, field coverage, and search yield of an exact release.

This is an offline diagnostic. Finishing the search plan does not establish a
complete catalog, and an observed maximum group size is not a verified API cap.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

COUNTRIES = ("ar", "co", "pe", "mx")
KEYS = ("country_code", "zone_slug", "store_id", "product_id")
FIELDS = ("volume_per_unit_ml", "pack_count", "total_volume_ml", "sugar_g_per_100ml",
          "sugar_g_per_serving", "serving_volume_ml", "abv_pct")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_verified(root: Path, record: dict) -> list[dict]:
    path = (root / record["data_root_relative_path"]).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("audit input escapes data root")
    if path.stat().st_size != record["bytes"] or digest(path) != record["sha256"]:
        raise ValueError(f"audit input checksum mismatch: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def numeric(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (ValueError, TypeError):
        return False


def country_report(plan: dict, rows: list[dict], queries: list[dict], candidates: list[dict]) -> dict:
    from rappi_co.beverages import SSB_CANDIDATE_FAMILIES

    country = plan["country_code"]
    slugs = [zone["slug"] for zone in plan["addresses"]]
    terms = plan["queries"]
    keys = [tuple(str(row.get(k) or "") for k in KEYS) for row in rows]
    if any(not all(key) or key[0] != country or key[1] not in slugs for key in keys):
        raise ValueError("missing or out-of-scope observation identity")
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate observation identities")
    candidate_keys = [tuple(str(row.get(k) or "") for k in KEYS) for row in candidates]
    if len(set(candidate_keys)) != len(candidate_keys) or not set(candidate_keys) <= set(keys):
        raise ValueError("candidate identities must be a unique subset of the audit")
    expected_candidates = {key for key, row in zip(keys, rows) if row["beverage_category"] == "ssb" or (
        row["beverage_category"] == "review" and row["beverage_subcategory"] in SSB_CANDIDATE_FAMILIES)}
    if set(candidate_keys) != expected_candidates:
        raise ValueError("candidate identities do not match the exact eligible cohort")
    by_key = dict(zip(keys, rows))
    for key, candidate in zip(candidate_keys, candidates):
        if any(candidate.get(field) != by_key[key].get(field) for field in
               (*FIELDS, "beverage_category", "beverage_subcategory")):
            raise ValueError("candidate quantitative fields or classification differ from the audit")
    if any(q["country_code"] != country or q["zone_slug"] not in slugs for q in queries):
        raise ValueError("out-of-scope query result")
    locations = []
    histogram = Counter()
    for zone in plan["addresses"]:
        group = [row for row in rows if row["zone_slug"] == zone["slug"]]
        searches = [q for q in queries if q["zone_slug"] == zone["slug"]]
        if [q["query"] for q in searches] != terms:
            raise ValueError("query results do not match the planned order and membership")
        if sum(int(q["new_items"]) for q in searches) != len(group):
            raise ValueError("query unique discoveries do not reconcile to audit observations")
        for query in searches:
            sizes = json.loads(query["group_sizes_json"])
            if (not isinstance(sizes, list) or any(type(n) is not int or n < 0 for n in sizes)
                    or len(sizes) != int(query["store_groups"])
                    or sum(sizes) != int(query["raw_rows"])):
                raise ValueError("invalid store group sizes")
            histogram.update(sizes)
        tail = searches[-5:]
        locations.append({
            "zone_slug": zone["slug"], "address": zone["address"],
            "latitude": zone["lat"], "longitude": zone["lng"],
            "requests": len(searches), "observations": len(group),
            "categories": dict(sorted(Counter(r["beverage_category"] for r in group).items())),
            "final_queries": [q["query"] for q in tail],
            "new_observations_from_final_queries": sum(int(q["new_items"]) for q in tail),
            "skipped_raw_rows": sum(int(q["skipped_rows"]) for q in searches),
        })
    max_size = max(histogram, default=0)
    cohorts = {"all_observations": rows, "ssb_candidates": candidates}
    for category in sorted({row["beverage_category"] for row in rows}):
        cohorts[category] = [row for row in rows if row["beverage_category"] == category]
    return {
        "country_code": country, "country": plan["country"], "city": plan["city"],
        "currency": plan["currency"], "full_protocol": plan["full_protocol"],
        "locations": locations, "raw_observations": len(rows),
        "ssb_candidate_observations": len(candidates),
        "unresolved_unknown_identity": sum(r["beverage_category"] == "review" and
                                           r["beverage_subcategory"] == "unknown" for r in rows),
        "source_brand_present": sum(bool(r.get("brand")) for r in rows),
        "search_description_present": sum(bool(r.get("short_description")) for r in rows),
        "observed_product_url_present": sum(bool(r.get("product_url")) for r in rows),
        "source_conflict_observations": sum(str(r.get("source_conflict", "")).lower() in {"true", "1"} for r in rows),
        "store_query_group_size_histogram": {str(k): histogram[k] for k in sorted(histogram)},
        "observed_maximum_group_size": max_size,
        "groups_at_observed_maximum": histogram[max_size] if histogram else 0,
        "historical_groups_at_least_25": sum(v for k, v in histogram.items() if k >= 25),
        "quantitative_field_coverage": {
            name: {"observations": len(cohort), **{
                field + "_present": sum(numeric(row.get(field)) for row in cohort) for field in FIELDS}}
            for name, cohort in cohorts.items()},
    }


def build_report(release_dir: Path, data_root: Path) -> dict:
    release = json.loads((release_dir / "manifest.json").read_text())
    records = release["workbooks"]
    if len(records) != 4 or {r["country_code"] for r in records} != set(COUNTRIES):
        raise ValueError("a four-country report requires exactly AR, CO, PE, and MX")
    countries = []
    provenance = []
    for code in COUNTRIES:
        record = next(r for r in records if r["country_code"] == code)
        path = release_dir / f"provenance_{code}.json"
        if digest(path) != record["provenance"]["sha256"]:
            raise ValueError(f"provenance checksum mismatch: {code}")
        manifest = json.loads(path.read_text())
        if manifest.get("complete") is not True or manifest["plan"]["country_code"] != code:
            raise ValueError(f"incomplete or mismatched provenance: {code}")
        outputs = manifest["outputs"]
        rows, queries, candidates = (read_verified(data_root, outputs[name]) for name in
                                     ("audit_csv", "query_yield_csv", "ssb_candidates_csv"))
        result = country_report(manifest["plan"], rows, queries, candidates)
        if result["raw_observations"] != record["raw_observations"]:
            raise ValueError(f"released observation count mismatch: {code}")
        countries.append(result)
        provenance.append({"country_code": code, "run_id": manifest["run_id"],
                           "provenance_sha256": digest(path)})
    return {
        "schema_version": 1,
        "observation_unit": "product-store-delivery-location; not unique products or national estimates",
        "catalog_completeness": "unknown",
        "interpretation": [
            "All planned requests can finish while searches omit relevant products or stores.",
            "Final-query discoveries depend on query order; continued yield does not prove saturation.",
            "Group-size maxima and histograms are observed diagnostics, not verified platform limits.",
            "Missing sugar is not zero; candidate identity does not establish sweetening.",
            "Candidate cohorts overlap review/items and must not be summed as disjoint categories.",
        ],
        "provenance": provenance, "countries": countries,
        "total_locations": sum(len(c["locations"]) for c in countries),
        "total_requests": sum(z["requests"] for c in countries for z in c["locations"]),
        "total_observations": sum(c["raw_observations"] for c in countries),
        "new_observations_from_final_queries": sum(z["new_observations_from_final_queries"]
                                                   for c in countries for z in c["locations"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, default=Path("datasets/beverages"))
    parser.add_argument("--data-root", type=Path, default=Path("data/beverages"))
    parser.add_argument("--output", type=Path, default=Path("datasets/beverages/coverage_audit.json"))
    args = parser.parse_args()
    report = build_report(args.release_dir, args.data_root)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "countries": len(report["countries"]),
                      "observations": report["total_observations"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
