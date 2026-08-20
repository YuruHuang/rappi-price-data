"""Tobacco classify orchestrator: search_items_<ts>.csv -> classifications.csv.

Fully offline. Pipeline per item (there is intentionally no Stage B — Stage A does the
keyword work, Stage C applies deterministic invariants on top):
  Stage A  keyword classifier (rappi_co/classify/tobacco_classifier.py)
  Stage C  deterministic overrides (rappi_co/classify/stage_c_overrides.py)

Run:
  python -m rappi_co.classify.run --input data/raw/<addr>/search_items_<ts>.csv \
                                  --out   data/co/processed/<addr>/classifications.csv
"""
from __future__ import annotations

import argparse
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from rappi_co.classify.stage_c_overrides import apply_overrides
from rappi_co.classify.tobacco_classifier import classify_item, load_lexicon, load_market_lexicon

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
logger = logging.getLogger(__name__)

OUT_COLS = [
    "product_id", "store_id", "store_type", "name", "brand",
    "menu_section", "menu_subsection",
    "primary_class", "product_type", "confidence", "method", "rationale", "flags",
]


def _read_items(path: str):
    import pandas as pd
    from rappi_co.parsers.store_payload import clean_name
    df = (pd.read_parquet(path) if path.endswith(".parquet")
          else pd.read_csv(path, dtype={"product_id": str, "store_id": str}))
    for col in ("product_id", "store_id"):
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)
    # Raw search files predate the collector's name cleaning, so scrub invisible zero-width
    # characters here too — both the classifier and the exported name then see clean text.
    for col in ("name", "brand"):
        if col in df.columns:
            df[col] = df[col].map(lambda v: clean_name(v) if isinstance(v, str) else v)
    return df


def run_classify(input_path: str, out_path: str | None = None,
                 country: str | None = None) -> str:
    import pandas as pd

    lex = load_market_lexicon(country) if country else load_lexicon()
    df = _read_items(input_path)
    logger.info("loaded %d menu items from %s", len(df), input_path)

    # stage A (keywords) + stage C (deterministic overrides), per item.
    out_rows = [apply_overrides({**rec, **classify_item(rec, lex).as_dict()},
                                study_mode=bool(country))
                for rec in df.to_dict(orient="records")]

    out_df = pd.DataFrame(out_rows)
    for c in OUT_COLS:
        if c not in out_df.columns:
            out_df[c] = None
    out_df = out_df[OUT_COLS]
    out_df["flags"] = out_df["flags"].apply(
        lambda f: "|".join(f) if isinstance(f, list) else (f or ""))

    if not out_path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = str(ROOT / "data" / (country or "co") / "processed"
                       / f"classifications_{ts}.csv")
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    work = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="", delete=False,
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp",
        ) as handle:
            work = Path(handle.name)
            out_df.to_csv(handle, index=False)
        # Classifications contain no secrets and are part of the portable research package.
        # Set the final public-read mode before replacement so a chmod failure cannot damage an
        # existing complete target.
        work.chmod(0o644)
        work.replace(target)
    finally:
        if work is not None and work.exists():
            work.unlink()

    counts = out_df["primary_class"].value_counts(dropna=False).to_dict()
    tob = out_df[out_df["primary_class"] == "tobacco"]
    logger.info("wrote %d rows -> %s", len(out_df), out_path)
    logger.info("primary_class: %s", counts)
    logger.info("tobacco product_type: %s",
                tob["product_type"].value_counts(dropna=False).to_dict())
    return out_path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--country", choices=["ar", "co", "pe", "mx"], default=None,
                   help="extend the classifier with reviewed brands for this market")
    p.add_argument("--input", required=True, help="menu_items CSV/parquet")
    p.add_argument("--out", default=None)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_classify(args.input, args.out, country=args.country)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
