import logging
import time

import requests

from screener.config import ONEMAP_SEARCH_URL

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, float] | None] = {}


def _clean_address(address: str) -> str:
    """Strip PropertyGuru district annotations like '(D25-28)' before geocoding."""
    import re
    return re.sub(r"\s*\(D\d+[-–]?\d*\)", "", address).strip()


def geocode(address: str, postal_code: str | None) -> tuple[float, float] | None:
    """Return (lat, lng) for an address using OneMap Singapore API."""
    search_val = postal_code if postal_code else _clean_address(address)
    if not search_val:
        return None

    if search_val in _cache:
        return _cache[search_val]

    result = _query_onemap(search_val)
    if result is None and postal_code:
        # Retry with cleaned address
        cleaned = _clean_address(address)
        if cleaned and cleaned != search_val:
            result = _query_onemap(cleaned)

    _cache[search_val] = result
    return result


def _query_onemap(search_val: str) -> tuple[float, float] | None:
    try:
        time.sleep(0.3)
        resp = requests.get(
            ONEMAP_SEARCH_URL,
            params={
                "searchVal": search_val,
                "returnGeom": "Y",
                "getAddrDetails": "Y",
                "pageNum": 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"[geocoder] OneMap request failed for '{search_val}': {e}")
        return None

    if not data.get("found") or not data.get("results"):
        return None

    r = data["results"][0]
    try:
        lat = float(r.get("LATITUDE") or r.get("Y", 0))
        lng = float(r.get("LONGITUDE") or r.get("LONGTITUDE") or r.get("X", 0))
        if lat == 0 or lng == 0:
            return None
        return lat, lng
    except (ValueError, TypeError):
        return None
