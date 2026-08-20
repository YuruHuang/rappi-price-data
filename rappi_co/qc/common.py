"""Shared config loader for the offline QC gate."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent          # repo root
THRESHOLDS_PATH = Path(__file__).resolve().parent / "thresholds_co.yml"


def load_thresholds() -> dict:
    with open(THRESHOLDS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
