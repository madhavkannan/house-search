import json
import logging

import httpx

from screener.config import SUPABASE_SERVICE_KEY, SUPABASE_URL
from screener.models import Listing

logger = logging.getLogger(__name__)

_HEADERS = lambda: {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}


def get_seen_ids() -> dict[str, set[str]]:
    """Return {source: set of source_ids} already in the database."""
    seen: dict[str, set[str]] = {"propertyguru": set(), "99co": set()}
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.warning("[db_writer] SUPABASE_URL or SUPABASE_SERVICE_KEY not set — skipping seen-ID check")
        return seen
    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/rest/v1/listings",
            params={"select": "source,source_id", "limit": 10000},
            headers=_HEADERS(),
            timeout=30,
        )
        resp.raise_for_status()
        for row in resp.json():
            src = row.get("source", "")
            sid = row.get("source_id", "")
            if src in seen:
                seen[src].add(sid)
    except Exception as e:
        logger.error(f"[db_writer] Failed to fetch seen IDs: {e}")
    return seen


def upsert_listing(listing: Listing) -> bool:
    """Insert listing; ignore if already exists. Returns True on success."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.warning("[db_writer] Supabase not configured — skipping upsert")
        return False
    payload = {
        "source": listing.source,
        "source_id": listing.source_id,
        "url": listing.url,
        "project_name": listing.project_name,
        "address": listing.address,
        "postal_code": listing.postal_code,
        "district": listing.district,
        "price": listing.price,
        "bedrooms": listing.bedrooms,
        "bathrooms": listing.bathrooms,
        "size_sqft": listing.size_sqft,
        "tenure": listing.tenure,
        "image_url": listing.image_url,
        "shelter_status": listing.shelter_status,
        "nearby_schools": listing.nearby_schools,
        "nearby_mrt": listing.nearby_mrt,
        "geocode_ok": listing.geocode_ok,
        "lat": listing.lat,
        "lng": listing.lng,
    }
    try:
        headers = {**_HEADERS(), "Prefer": "resolution=ignore-duplicates"}
        resp = httpx.post(
            f"{SUPABASE_URL}/rest/v1/listings",
            content=json.dumps(payload),
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"[db_writer] Failed to upsert {listing.source}/{listing.source_id}: {e}")
        return False
