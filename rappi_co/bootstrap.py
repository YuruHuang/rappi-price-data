"""Lock each Bogotá delivery address into a real Rappi session and save its cookies.

if you only set browser geolocation, rappi auto-locates to a generic bogotá centroid
(currentLocation.autoLocation=true) and ignores the exact address. so we craft the
currentLocation cookie ourselves (address coords + autoLocation=false); rappi accepts it
and even assigns it an id. one storage_state per address -> data/state/<slug>.json.

    python -m rappi_co.bootstrap --all
    python -m rappi_co.bootstrap --address calle-19-centro      # may repeat
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZONES = ROOT / "config" / "zones_co.yml"
STATE_DIR = ROOT / "data" / "state"
BASE = "https://www.rappi.com.co"


def _current_location(lat: float, lng: float, address: str) -> str:
    # rappi reads this cookie for the active delivery location. autoLocation=false marks
    # it as an explicit user choice (a real address) rather than an ip/gps guess.
    obj = {"city": "Bogotá", "lat": lat, "lng": lng, "url": "bogota",
           "address": address, "autoLocation": False, "active": True}
    blob = urllib.parse.quote(json.dumps(obj, ensure_ascii=False))
    return base64.b64encode(blob.encode()).decode()


def _decode_location(value: str) -> dict:
    return json.loads(urllib.parse.unquote(base64.b64decode(value).decode()))


def verify_locked(state_path: Path, lat: float, lng: float, tol: float = 0.05):
    # confirm the saved session is actually pinned to this address, not auto-located.
    st = json.loads(Path(state_path).read_text())
    cur = next((c for c in st.get("cookies", []) if c["name"] == "currentLocation"), None)
    if not cur:
        return False, "no currentLocation cookie"
    loc = _decode_location(cur["value"])
    if loc.get("autoLocation") is not False:
        return False, f"autoLocation={loc.get('autoLocation')} — address not locked"
    if abs(float(loc.get("lat", 0)) - lat) > tol or abs(float(loc.get("lng", 0)) - lng) > tol:
        return False, f"coords {loc.get('lat')},{loc.get('lng')} != {lat},{lng}"
    return True, f"locked at {loc.get('lat')},{loc.get('lng')} ({loc.get('address')})"


async def lock_address(pw, zone: dict, headless: bool = True) -> Path:
    slug, lat, lng = zone["slug"], float(zone["lat"]), float(zone["lng"])
    browser = await pw.chromium.launch(headless=headless)
    ctx = await browser.new_context(
        locale="es-CO", timezone_id="America/Bogota",
        geolocation={"latitude": lat, "longitude": lng}, permissions=["geolocation"],
        user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/121.0 Safari/537.36"),
    )
    await ctx.add_cookies([{
        "name": "currentLocation",
        "value": _current_location(lat, lng, zone.get("address", "Bogotá")),
        "domain": ".rappi.com.co", "path": "/",
    }])
    page = await ctx.new_page()
    # navigate so rappi layers its session cookies on top of our pinned location.
    await page.goto(BASE, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(5000)
    await page.goto(f"{BASE}/tiendas/tipo/market", wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(3000)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    out = STATE_DIR / f"{slug}.json"
    await ctx.storage_state(path=str(out))
    await browser.close()
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", action="append", default=[], help="zone slug; may repeat")
    ap.add_argument("--all", action="store_true", help="bootstrap every address in zones_co.yml")
    args = ap.parse_args()

    from rappi_co.configs import load_zones
    zones = load_zones(ZONES)
    if args.address:
        zones = [z for z in zones if z["slug"] in set(args.address)]
    elif not args.all:
        ap.error("pass --all or --address <slug>")
    if not zones:
        print("no matching zones"); return 1

    from playwright.async_api import async_playwright
    rc = 0
    async with async_playwright() as pw:
        for z in zones:
            out = await lock_address(pw, z)
            ok, msg = verify_locked(out, float(z["lat"]), float(z["lng"]))
            print(f"[{z['slug']}] {'OK ' if ok else 'FAIL'} {msg} -> {out}", flush=True)
            rc = rc or (0 if ok else 2)
    return rc


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
