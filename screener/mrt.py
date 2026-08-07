import json
import logging
from functools import lru_cache

from screener.config import MRT_WALK_M, MRT_FILE
from screener.schools import haversine_km

logger = logging.getLogger(__name__)

MRT_WALK_KM = MRT_WALK_M / 1000.0


@lru_cache(maxsize=1)
def load_mrt_stations() -> list[dict]:
    if not MRT_FILE.exists():
        logger.warning(f"[mrt] {MRT_FILE} not found — run scripts/fetch_mrt_stations.py first")
        return []
    try:
        return json.loads(MRT_FILE.read_text())
    except Exception as e:
        logger.error(f"[mrt] Failed to load MRT stations: {e}")
        return []


def mrt_within_walk(lat: float, lng: float) -> list[str]:
    stations = load_mrt_stations()
    nearby = []
    for s in stations:
        try:
            d_km = haversine_km(lat, lng, s["lat"], s["lng"])
            d_m = d_km * 1000
            if d_m <= MRT_WALK_M:
                nearby.append(f"{s['name']} ({int(d_m)}m)")
        except (KeyError, TypeError):
            continue
    return sorted(nearby, key=lambda x: int(x.rsplit("(", 1)[1].rstrip("m)")))
