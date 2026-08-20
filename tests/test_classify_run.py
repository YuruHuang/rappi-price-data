import stat
from pathlib import Path

import pandas as pd
import pytest

from rappi_co.classify.run import run_classify


def _raw_items(path: Path) -> None:
    path.write_text(
        "product_id,store_id,store_type,name,brand,menu_section,menu_subsection\n"
        "000123,000045,market,Marlboro Rojo 20 Und,Marlboro,Cigarrillos,\n",
        encoding="utf-8-sig",
    )


def test_run_classify_preserves_string_identifiers(tmp_path):
    source = tmp_path / "items.csv"
    target = tmp_path / "classifications.csv"
    _raw_items(source)

    run_classify(str(source), str(target))

    classified = pd.read_csv(target, dtype=str, keep_default_na=False)
    assert classified.loc[0, "product_id"] == "000123"
    assert classified.loc[0, "store_id"] == "000045"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_run_classify_replaces_private_target_with_shareable_mode(tmp_path):
    source = tmp_path / "items.csv"
    target = tmp_path / "classifications.csv"
    _raw_items(source)
    target.write_text("old\n", encoding="utf-8")
    target.chmod(0o600)

    run_classify(str(source), str(target))

    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_run_classify_replaces_target_only_after_success(tmp_path, monkeypatch):
    source = tmp_path / "items.csv"
    target = tmp_path / "classifications.csv"
    _raw_items(source)
    target.write_text("existing complete classification\n", encoding="utf-8")

    def fail_write(*args, **kwargs):
        raise OSError("simulated interrupted write")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_write)
    with pytest.raises(OSError, match="interrupted"):
        run_classify(str(source), str(target))

    assert target.read_text(encoding="utf-8") == "existing complete classification\n"
    assert not list(tmp_path.glob(".classifications.csv.*.tmp"))


def test_run_classify_keeps_existing_target_when_chmod_fails(tmp_path, monkeypatch):
    source = tmp_path / "items.csv"
    target = tmp_path / "classifications.csv"
    _raw_items(source)
    target.write_text("existing complete classification\n", encoding="utf-8")
    target.chmod(0o600)
    original_chmod = Path.chmod

    def fail_temp_chmod(path, mode, *args, **kwargs):
        if path.suffix == ".tmp":
            raise OSError("simulated chmod failure")
        return original_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "chmod", fail_temp_chmod)
    with pytest.raises(OSError, match="chmod failure"):
        run_classify(str(source), str(target))

    assert target.read_text(encoding="utf-8") == "existing complete classification\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".classifications.csv.*.tmp"))
