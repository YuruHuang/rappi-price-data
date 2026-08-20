"""Regression lock for the adversarial FP/FN hardening pass.

`tobacco_gold_co_adversarial.csv` is a regression set of Colombian hard cases (real CO
cigarette brands like Pielroja/Boston/Mustang/Caribe, collision traps like Boston
cookies / Camel backpacks / Premier cream / Imperial beer, vapes + zero-nic, heated
tobacco / pouches / rolling & hookah tobacco, NRT vs non-nicotine cessation,
paraphernalia + candy, typos/variants, scope edges, and home-improvement/paint colour
collisions where "tabaco" names a wood finish or sealant shade). Every case is consistent
with the current keywords_co.yml + classifier (P=R=1.0). Extend it when new catalog
vocabulary is reviewed and labeled.

Run: python -m pytest tests/test_adversarial_regression.py -q
"""
from pathlib import Path

from rappi_co.classify.tobacco_classifier import classify_item, load_lexicon

GOLD = Path(__file__).resolve().parent.parent / "rappi_co" / "qc" / "gold" / "tobacco_gold_co_adversarial.csv"


def _confusion():
    import csv
    lex = load_lexicon()
    tp = fp = fn = tn = 0
    fails = []
    with open(GOLD, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["has_antismoking"] = str(row.get("has_antismoking", "")).lower() == "true"
            pred = classify_item(row, lex).primary_class
            gold = row["gold_label"]
            if gold == "tobacco" and pred == "tobacco":
                tp += 1
            elif gold == "out_of_scope" and pred == "out_of_scope":
                tn += 1
            elif gold == "out_of_scope":
                fp += 1; fails.append(("FP", row["name"]))
            else:
                fn += 1; fails.append(("FN", row["name"]))
    return tp, fp, fn, tn, fails


def test_adversarial_precision_recall():
    tp, fp, fn, tn, fails = _confusion()
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    # The hardened classifier scores 1.0/1.0 on this set; allow a tiny recall floor
    # for future lexicon churn but keep precision perfect (no false positives).
    assert precision == 1.0, f"precision regressed: {precision:.4f}; fails={fails}"
    assert recall >= 0.98, f"recall regressed: {recall:.4f}; fails={fails}"
    assert tp + fp + fn + tn == 70
