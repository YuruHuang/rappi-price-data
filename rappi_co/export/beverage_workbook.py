"""Present a completed beverage run in the published country workbook format.

This only reads saved, verified outputs. It does not collect or reclassify data.
For an existing country-team run:

    python -m rappi_co.export.beverage_workbook --run-dir data/updates/co_demo_02
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from rappi_co.beverages import SSB_CANDIDATE_FAMILIES
from rappi_co.export.integrated_deliverable import canonical_row, observation_key
from rappi_co.export.product_workbook import write_product_workbook
from rappi_co.release_update import _csv, _manifest_output, _record


SHEETS = ("SSBs", "Water", "Alcohol")


def export_beverage_workbook(manifest_path: Path, data_root: Path, out: Path) -> dict:
    """Write three clean category tabs from the exact saved candidate membership."""
    manifest_path, data_root, out = Path(manifest_path).resolve(), Path(data_root).resolve(), Path(out)
    sidecar = out.with_suffix(".manifest.json")
    if out.exists() or sidecar.exists():
        raise FileExistsError(f"Choose a new workbook filename: {out}")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    plan = manifest.get("plan") or {}
    code = plan.get("country_code")
    if manifest.get("complete") is not True or code not in {"ar", "co", "pe", "mx"} or not manifest.get("run_id"):
        raise ValueError("Expected a completed beverage source manifest")
    paths = {kind: _manifest_output(manifest, kind, data_root)
             for kind in ("audit_csv", "ssb_candidates_csv")}
    _, audit = _csv(paths["audit_csv"])
    _, candidates = _csv(paths["ssb_candidates_csv"])
    counts = manifest.get("counts") or {}
    if counts.get("audit") != len(audit) or counts.get("ssb_candidates") != len(candidates):
        raise ValueError("Saved beverage counts differ from the source manifest")
    keyed = {}
    for row in audit:
        key = observation_key(row)
        if row["country_code"] != code or key in keyed:
            raise ValueError("Wrong country or duplicate beverage observation")
        keyed[key] = row
    candidate_map = {}
    for row in candidates:
        key = observation_key(row)
        source = keyed.get(key)
        if source is None or key in candidate_map:
            raise ValueError("SSB candidates must be a unique subset of the saved audit")
        if any(value != source.get(field) for field, value in row.items() if field != "ssb_candidate_status"):
            raise ValueError("SSB candidate content differs from its audit observation")
        status = "confirmed_sugar_sweetened" if source.get("beverage_category") == "ssb" else "sweetening_unconfirmed"
        if row.get("ssb_candidate_status") != status:
            raise ValueError("SSB candidate status differs from its classification")
        candidate_map[key] = row
    expected_candidates = {key for key, row in keyed.items()
                           if row.get("beverage_category") == "ssb" or
                           (row.get("beverage_category") == "review" and
                            row.get("beverage_subcategory") in SSB_CANDIDATE_FAMILIES)}
    if set(candidate_map) != expected_candidates:
        raise ValueError("Saved SSB membership differs from the recorded classifications")
    expected = {name: [] for name in SHEETS}
    for index, row in enumerate(audit, 2):
        normalized = canonical_row(row, "beverages", manifest["run_id"],
                                   str(paths["audit_csv"].relative_to(data_root)), index, candidate_map)
        name = {"SSB_candidates": "SSBs", "Water": "Water", "Alcohol": "Alcohol"}.get(normalized["reporting_group"])
        if name:
            expected[name].append(normalized)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".beverage-products-", dir=out.parent) as directory:
        temporary = Path(directory) / out.name
        write_product_workbook(temporary, plan.get('country'), expected)
        # Refuse to publish if a saved input changed while it was being read.
        if manifest_path.read_bytes() != manifest_bytes:
            raise ValueError("Beverage source manifest changed during export")
        for kind, path in paths.items():
            if _manifest_output(manifest, kind, data_root) != path:
                raise ValueError("Beverage source changed during export")
        result = {
            "status": "verified_beverage_product_workbook", "country_code": code,
            "source_run_id": manifest["run_id"], "sheets": list(SHEETS),
            "rows": {name: len(rows) for name, rows in expected.items()},
            "source_manifest": {"path": str(manifest_path), "sha256": hashlib.sha256(manifest_bytes).hexdigest()},
            "sources": {kind: _record(path) for kind, path in paths.items()},
            "notes": ["SSBs contains the saved screening cohort, including unconfirmed sweetening.",
                      "Blank measurements are unknown, not zero. Review, comparison and excluded records remain in the source outputs.",
                      "Column labels, number formats, colors and hidden evidence fields match the published country product workbooks."],
        }
        if out.exists() or sidecar.exists():
            raise FileExistsError(f"Choose a new workbook filename: {out}")
        temporary.replace(out)
        result["workbook"] = _record(out.resolve())
        sidecar.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def export_saved_run(run_dir: Path, out: Path | None = None) -> dict:
    """Locate one source manifest in a country-team run, including moved folders."""
    run_dir = Path(run_dir).resolve()
    wrapper = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if wrapper.get("status") != "completed_country_collection" or wrapper.get("scope") != "beverages":
        raise ValueError("Choose a completed beverage-only country-team run folder")
    source = wrapper.get("result", {}).get("deliverable", {}).get("manifest")
    if not source:
        raise ValueError("The run does not identify its beverage source manifest")
    root = run_dir / "source"
    matches = list(root.glob(f"*/processed/*/{Path(source).name}"))
    if len(matches) != 1:
        raise ValueError("Cannot locate exactly one saved beverage source manifest")
    source_manifest = json.loads(matches[0].read_text(encoding="utf-8"))
    if source_manifest.get("plan", {}).get("country_code") != wrapper.get("country_code"):
        raise ValueError("Saved run and beverage manifest countries differ")
    target = Path(out) if out is not None else run_dir / "country_products" / f"{wrapper['country_code']}_beverages_clean.xlsx"
    return export_beverage_workbook(matches[0], root, target)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path, help="completed beverage-only run folder")
    parser.add_argument("--out", type=Path, help="new workbook filename; defaults to country_products/COUNTRY_beverages_clean.xlsx")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(export_saved_run(args.run_dir, args.out), ensure_ascii=False, indent=2))
    except (OSError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
