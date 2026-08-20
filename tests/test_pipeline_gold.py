"""offline gold-set gate + enrichment + import smoke for the CO tobacco pipeline.

run:  PYTHONPATH=. pytest tests/test_pipeline_gold.py -q
"""
import importlib
from pathlib import Path

import pytest

GOLD = Path(__file__).resolve().parent.parent / "rappi_co" / "qc" / "gold" / "tobacco_gold_co.csv"


def test_gold_precision_recall_meets_gate():
    # the keyword classifier alone must clear the precision/recall gate on the curated gold set.
    from rappi_co.qc.gate import run_qc
    from rappi_co.qc.common import load_thresholds
    res = run_qc(gold_path=str(GOLD))
    m = res["metrics"]
    tt = load_thresholds()["tobacco_team"]
    assert m["basis"] == "gold_set"
    assert m["precision"] >= tt["precision_min"], m
    assert m["recall"] >= tt["recall_min"], m
    assert res["gate"] == "PASS", m
    assert m["confusion"]["fp"] == 0 and m["confusion"]["fn"] == 0, m["confusion"]


def test_enrich_nicotine_and_puff():
    from rappi_co.enrich.tobacco_fields import enrich_tobacco_fields
    assert enrich_tobacco_fields("Nic salt 20mg/ml frutilla")["nicotine_mg_per_ml"] == 20.0
    pouch = enrich_tobacco_fields("ZYN bolsita de nicotina 6mg")
    assert pouch["nicotine_mg_per_pouch"] == 6.0
    assert pouch["nicotine_mg_per_ml"] is None
    assert enrich_tobacco_fields("Elf Bar 600 puffs sandia")["puff_count"] == 600
    none = enrich_tobacco_fields("Coca Cola 1.5L")
    assert none["nicotine_mg_per_ml"] is None and none["puff_count"] is None


@pytest.mark.parametrize("mod", [
    "rappi_co.classify.tobacco_classifier",
    "rappi_co.classify.stage_c_overrides",
    "rappi_co.classify.run",
    "rappi_co.enrich.tobacco_fields",
    "rappi_co.export.tobacco_deliverable",
    "rappi_co.qc.common",
    "rappi_co.qc.gate",
])
def test_modules_import(mod):
    # every shipped module imports cleanly in a clean environment.
    assert importlib.import_module(mod) is not None
