import hashlib
import json
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "datasets" / "manifest.json"
EXPECTED_SHEETS = ["items", "stores", "locations", "summary", "data_dictionary"]


def test_published_workbooks_match_release_manifest():
    release = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert release["schema_version"] == 1
    assert len(release["files"]) == 4

    for record in release["files"]:
        path = ROOT / record["path"]
        payload = path.read_bytes()
        assert len(payload) == record["bytes"], path
        assert hashlib.sha256(payload).hexdigest() == record["sha256"], path

        workbook = load_workbook(path, data_only=False, read_only=False)
        assert workbook.sheetnames == EXPECTED_SHEETS, path
        assert workbook.active.title == "summary", path
        assert workbook["items"].max_row - 1 == record["observations"], path
        assert (workbook["stores"].max_row - 1
                == record["store_location_observations"]), path
        assert workbook["locations"].max_row == 3, path
        assert workbook["data_dictionary"].max_row == 72, path

        for sheet in workbook.worksheets:
            assert sheet.sheet_state == "visible", (path, sheet.title)
            assert sheet.freeze_panes == "A2", (path, sheet.title)
            assert sheet.auto_filter.ref == sheet.dimensions, (path, sheet.title)
            assert not sheet.tables, (path, sheet.title)
            assert not any(
                cell.data_type == "f"
                for row in sheet.iter_rows()
                for cell in row
            ), (path, sheet.title)
        workbook.close()
