"""
One-time script to fetch MOE primary schools from data.gov.sg and geocode
them via OneMap. Run once before first deploy:

    python scripts/fetch_schools.py

Output: data/moe_primary_schools.json
"""

import json
import time
from pathlib import Path

import requests

DATA_GOV_URL = "https://data.gov.sg/api/action/datastore_search"
# General Information of Schools dataset
RESOURCE_ID = "d_688b934f82c1059ed0a6993d2a829089"

ONEMAP_URL = "https://www.onemap.gov.sg/api/common/elastic/search"
OUT_FILE = Path(__file__).parent.parent / "data" / "moe_primary_schools.json"


def fetch_all_schools() -> list[dict]:
    schools = []
    offset = 0
    limit = 100
    while True:
        resp = requests.get(
            DATA_GOV_URL,
            params={"resource_id": RESOURCE_ID, "limit": limit, "offset": offset},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        records = data.get("result", {}).get("records", [])
        if not records:
            break
        schools.extend(records)
        total = data.get("result", {}).get("total", 0)
        offset += limit
        if offset >= total:
            break
    return schools


def geocode_postal(postal: str) -> tuple[float, float] | None:
    time.sleep(0.3)
    try:
        resp = requests.get(
            ONEMAP_URL,
            params={"searchVal": postal, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": 1},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("found") or not data.get("results"):
            return None
        r = data["results"][0]
        lat = float(r.get("LATITUDE") or 0)
        lng = float(r.get("LONGITUDE") or r.get("LONGTITUDE") or 0)
        return (lat, lng) if lat and lng else None
    except Exception:
        return None


def main():
    print("Fetching MOE school records from data.gov.sg …")
    all_schools = fetch_all_schools()
    print(f"  Total records: {len(all_schools)}")

    primary = [
        s for s in all_schools
        if (s.get("mainlevel_code") or s.get("nature_code") or "").upper() in ("PRIMARY", "MIXED LEVELS")
        and s.get("postal_code")
    ]
    print(f"  Primary schools with postal code: {len(primary)}")

    results = []
    for i, s in enumerate(primary):
        name = s.get("school_name") or s.get("name") or ""
        postal = str(s.get("postal_code") or "").zfill(6)
        coords = geocode_postal(postal)
        if coords:
            results.append({"name": name, "postal_code": postal, "lat": coords[0], "lng": coords[1]})
            print(f"  [{i+1}/{len(primary)}] {name} → {coords}")
        else:
            print(f"  [{i+1}/{len(primary)}] {name} — geocoding failed, skipping")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(results)} schools to {OUT_FILE}")


if __name__ == "__main__":
    main()
