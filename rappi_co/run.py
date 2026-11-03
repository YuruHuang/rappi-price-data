"""Collect fresh listings for a country team's own locations and search plan.

Start with --dry-run, review the request budget, then use --collect with the same
arguments. Every collection writes a new output directory and saves its plan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
from datetime import datetime, timezone

from rappi_co import beverages, release_update, study
from rappi_co.locations import validate_location_scope


def _queries(text: str | None, path: Path | None) -> list[str] | None:
    if text is not None and path is not None:
        raise ValueError("choose a comma-separated query list or a terms file, not both")
    if path is not None:
        from rappi_co.terms import load_terms_file
        return load_terms_file(path)
    if text is None:
        return None
    result = list(dict.fromkeys(term.strip() for term in text.split(",") if term.strip()))
    if not result:
        raise ValueError("at least one search term is required")
    return result


def _record(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", required=True, choices=study.COUNTRIES,
                        help="country served by this collection: ar, co, pe, or mx")
    parser.add_argument("--locations-file", type=Path,
                        help="CSV, TSV, XLSX, JSON, or YAML delivery locations; no fixed count")
    parser.add_argument("--address", action="append", help="optional location slug filter; repeatable")
    parser.add_argument("--scope", choices=("both", "tobacco", "beverages"), default="both")
    parser.add_argument("--terms", help="comma-separated queries for one selected scope")
    parser.add_argument("--terms-file", type=Path, help="queries file for one selected scope")
    parser.add_argument("--tobacco-terms", help="comma-separated tobacco queries")
    parser.add_argument("--tobacco-terms-file", type=Path)
    parser.add_argument("--beverage-terms", help="comma-separated beverage queries")
    parser.add_argument("--beverage-terms-file", type=Path)
    parser.add_argument("--out", required=True, type=Path, help="new output directory")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print the plan without network requests")
    mode.add_argument("--collect", action="store_true", help="collect fresh Rappi listings")
    parser.add_argument("--resume", action="store_true", help="resume an interrupted both-scope package")
    parser.add_argument("--min-delay", type=float, default=1.0)
    parser.add_argument("--max-delay", type=float, default=3.0)
    args = parser.parse_args(argv)
    try:
        input_files = [path for path in (args.locations_file, args.terms_file,
                                         args.tobacco_terms_file, args.beverage_terms_file)
                       if path is not None]
        input_records = [_record(path) for path in input_files]
        if (not math.isfinite(args.min_delay) or not math.isfinite(args.max_delay)
                or not 0 <= args.min_delay <= args.max_delay):
            raise ValueError("delays must satisfy 0 <= min-delay <= max-delay")
        if args.locations_file is not None:
            validate_location_scope(args.locations_file, [args.country])
        if args.scope == "both" and (args.terms is not None or args.terms_file is not None):
            raise ValueError("with --scope both use --tobacco-terms[-file] and --beverage-terms[-file]")
        if args.scope == "both" and args.address:
            raise ValueError("for --scope both, put the intended points in the locations file; --address is for a single scope")
        if args.resume and (not args.collect or args.scope != "both"):
            raise ValueError("--resume requires --collect and --scope both")
        tobacco_terms = _queries(args.tobacco_terms, args.tobacco_terms_file)
        beverage_terms = _queries(args.beverage_terms, args.beverage_terms_file)
        if args.scope == "tobacco":
            if beverage_terms is not None:
                raise ValueError("beverage terms require --scope beverages or both")
            if args.terms is not None or args.terms_file is not None:
                if tobacco_terms is not None:
                    raise ValueError("use --terms[-file] or --tobacco-terms[-file], not both")
                tobacco_terms = _queries(args.terms, args.terms_file)
        elif args.scope == "beverages":
            if tobacco_terms is not None:
                raise ValueError("tobacco terms require --scope tobacco or both")
            if args.terms is not None or args.terms_file is not None:
                if beverage_terms is not None:
                    raise ValueError("use --terms[-file] or --beverage-terms[-file], not both")
                beverage_terms = _queries(args.terms, args.terms_file)
        plan_kwargs = {"locations_file": args.locations_file}
        plans = {}
        if args.scope in {"both", "tobacco"}:
            plans["tobacco"] = study.plan_country(args.country, args.address, tobacco_terms, **plan_kwargs)
        if args.scope in {"both", "beverages"}:
            plans["beverages"] = beverages.plan_country(args.country, args.address, beverage_terms, **plan_kwargs)
        planned_requests = sum(plan["requests"] for plan in plans.values())
        if input_records != [_record(path) for path in input_files]:
            raise RuntimeError("an input file changed while the plan was being read; retry with stable inputs")
        report = {"country_code": args.country, "scope": args.scope,
                  "planned_search_requests": planned_requests, "plans": plans,
                  "input_files": input_records,
                  "note": "Requests are sequential; retries may add requests. Search coverage is finite."}
        if args.dry_run:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if args.scope == "both":
            query_files = [path for path in (args.tobacco_terms_file, args.beverage_terms_file)
                           if path is not None]
            result = release_update.collect_and_build(
                args.out, args.min_delay, args.max_delay, resume=args.resume,
                countries=[args.country], locations_file=args.locations_file,
                tobacco_terms=tobacco_terms, beverage_terms=beverage_terms,
                **({"input_files": query_files} if query_files else {}),
            )
            print(json.dumps({"status": result["status"], "output": str(args.out.resolve()),
                              "workbooks": str((args.out / "country_products").resolve())}, indent=2))
            return 0
        if args.out.exists():
            raise FileExistsError(f"destination must be new: {args.out}")
        args.out.mkdir(parents=True, exist_ok=False)
        inputs = args.out / "inputs"
        inputs.mkdir()
        for index, path in enumerate(input_files, 1):
            shutil.copyfile(path, inputs / f"{index:02d}_{path.name}")
        (args.out / "plan.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        runner = study if args.scope == "tobacco" else beverages
        terms = tobacco_terms if args.scope == "tobacco" else beverage_terms
        try:
            collected = runner.run_country(
                args.country, addresses=args.address, terms=terms,
                data_root=args.out / "source", locations_file=args.locations_file,
                min_delay=args.min_delay, max_delay=args.max_delay,
            )
            if input_records != [_record(path) for path in input_files]:
                raise RuntimeError("an input file changed during collection; keep this run for diagnosis and start a new run")
            products = args.out / "country_products"
            products.mkdir()
            workbook = products / f"{args.country}_{args.scope}.xlsx"
            shutil.copyfile(collected["deliverable"]["xlsx"], workbook)
            manifest = {"status": "completed_country_collection", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                        **report, "result": collected, "workbook": _record(workbook)}
            (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"status": manifest["status"], "workbook": str(workbook.resolve()),
                              "manifest": str((args.out / "manifest.json").resolve())}, indent=2))
        except BaseException as error:
            (args.out / "FAILED.json").write_text(json.dumps({"status": "failed", "error": str(error)}, indent=2) + "\n", encoding="utf-8")
            raise
        return 0
    except (ValueError, OSError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
