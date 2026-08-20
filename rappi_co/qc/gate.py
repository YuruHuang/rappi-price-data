"""Offline gold gate: run the keyword classifier over the labeled gold set and measure
precision/recall against the thresholds. Runs offline, no API key.

  python -m rappi_co.qc.gate --gold rappi_co/qc/gold/tobacco_gold_co.csv
"""
from __future__ import annotations

import argparse
import json
import logging

from rappi_co.classify.stage_c_overrides import apply_overrides
from rappi_co.classify.tobacco_classifier import classify_item, load_lexicon
from rappi_co.qc.common import load_thresholds

logger = logging.getLogger(__name__)


def _predict(rec: dict, lex: dict) -> str:
    res = apply_overrides({**rec, **classify_item(rec, lex).as_dict()})
    return res.get("primary_class", "out_of_scope")


def run_qc(gold_path: str, thresholds: dict | None = None) -> dict:
    """classify the gold set and score precision/recall against its gold_label column."""
    import pandas as pd
    lex = load_lexicon()
    tt = (thresholds or load_thresholds()).get("tobacco_team", {})
    pmin, rmin = tt.get("precision_min", 0.98), tt.get("recall_min", 0.97)

    df = pd.read_csv(gold_path)
    tp = fp = fn = tn = 0
    for rec in df.to_dict(orient="records"):
        gold_t = str(rec.get("gold_label")) == "tobacco"
        pred_t = _predict(rec, lex) == "tobacco"
        if gold_t and pred_t:
            tp += 1
        elif pred_t and not gold_t:
            fp += 1
        elif gold_t and not pred_t:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    reasons = []
    if precision < pmin:
        reasons.append(f"precision {precision:.3f} < {pmin}")
    if recall < rmin:
        reasons.append(f"recall {recall:.3f} < {rmin}")
    return {
        "gate": "FAIL" if reasons else "PASS",
        "metrics": {"precision": round(precision, 4), "recall": round(recall, 4),
                    "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn}, "basis": "gold_set"},
        "reasons": reasons,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--gold", required=True, help="labeled gold CSV (needs a gold_label column)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    res = run_qc(args.gold)
    print(f"GATE={res['gate']}  metrics={json.dumps(res['metrics'], ensure_ascii=False)}")
    if res["reasons"]:
        print("reasons:", "; ".join(res["reasons"]))
    return 0 if res["gate"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
