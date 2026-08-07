import json
import math
import logging
from functools import lru_cache

from screener.config import SCHOOL_KM, SCHOOLS_FILE

logger = logging.getLogger(__name__)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


@lru_cache(maxsize=1)
def load_schools() -> list[dict]:
    if not SCHOOLS_FILE.exists():
        logger.warning(f"[schools] {SCHOOLS_FILE} not found — run scripts/fetch_schools.py first")
        return []
    try:
        return json.loads(SCHOOLS_FILE.read_text())
    except Exception as e:
        logger.error(f"[schools] Failed to load schools: {e}")
        return []


def schools_within_radius(lat: float, lng: float) -> list[str]:
    schools = load_schools()
    nearby = []
    for s in schools:
        try:
            d = haversine_km(lat, lng, s["lat"], s["lng"])
            if d <= SCHOOL_KM:
                nearby.append(f"{s['name']} ({d:.1f}km)")
        except (KeyError, TypeError):
            continue
    return sorted(nearby)
