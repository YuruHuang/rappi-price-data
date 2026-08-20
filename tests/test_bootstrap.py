# Tests for the per-address location lock, including silent fallback to a generic
# auto-located Bogotá session.
import base64
import json
import urllib.parse

from rappi_co.bootstrap import _current_location, verify_locked


def _state(tmp_path, loc_value):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"cookies": [{"name": "currentLocation", "value": loc_value}]}))
    return p


def _encode(obj):
    return base64.b64encode(urllib.parse.quote(json.dumps(obj, ensure_ascii=False)).encode()).decode()


def test_current_location_marks_explicit_choice():
    obj = json.loads(urllib.parse.unquote(base64.b64decode(_current_location(4.6093, -74.0682, "Calle 19")).decode()))
    assert obj["autoLocation"] is False
    assert obj["lat"] == 4.6093 and obj["lng"] == -74.0682
    assert obj["address"] == "Calle 19"


def test_verify_locked_passes_for_real_address(tmp_path):
    p = _state(tmp_path, _current_location(4.6093, -74.0682, "Calle 19 #2A-10"))
    ok, msg = verify_locked(p, 4.6093, -74.0682)
    assert ok, msg


def test_verify_locked_fails_on_autolocation(tmp_path):
    # City centroid + autoLocation=true must not count as locked.
    p = _state(tmp_path, _encode({"city": "Bogotá", "lat": 4.6755, "lng": -74.0499,
                                  "address": "Bogotá", "autoLocation": True, "active": True}))
    ok, msg = verify_locked(p, 4.6093, -74.0682)
    assert not ok and "autoLocation" in msg


def test_verify_locked_fails_on_wrong_coords(tmp_path):
    p = _state(tmp_path, _current_location(4.70, -74.14, "somewhere else"))
    ok, _ = verify_locked(p, 4.6093, -74.0682)
    assert not ok


def test_verify_locked_fails_without_cookie(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"cookies": []}))
    ok, msg = verify_locked(p, 4.6093, -74.0682)
    assert not ok and "no currentLocation" in msg
