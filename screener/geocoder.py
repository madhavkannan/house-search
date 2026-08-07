import logging
import re
import time

import requests

from screener.config import ONEMAP_SEARCH_URL

logger = logging.getLogger(__name__)

# Singapore postal code prefix (first 2 digits) → planning district
_POSTAL_PREFIX_TO_DISTRICT: dict[str, str] = {
    **{f"{p:02d}": "D01" for p in range(1, 9)},
    **{f"{p:02d}": "D02" for p in range(9, 11)},
    **{f"{p:02d}": "D03" for p in range(11, 13)},
    "13": "D04",
    **{f"{p:02d}": "D05" for p in range(14, 16)},
    "16": "D06",
    "17": "D07",
    **{f"{p:02d}": "D08" for p in range(18, 20)},
    **{f"{p:02d}": "D09" for p in range(20, 22)},
    **{f"{p:02d}": "D10" for p in range(22, 24)},
    **{f"{p:02d}": "D11" for p in range(24, 28)},
    **{f"{p:02d}": "D12" for p in range(28, 31)},
    **{f"{p:02d}": "D13" for p in range(31, 34)},
    "34": "D14", "35": "D14", "37": "D14",
    "36": "D15",
    **{f"{p:02d}": "D15" for p in range(38, 46)},
    **{f"{p:02d}": "D16" for p in range(46, 49)},
    **{f"{p:02d}": "D17" for p in range(49, 51)},
    "51": "D18", "54": "D18", "55": "D18",
    "52": "D19", "53": "D19", "56": "D19", "57": "D19",
    "58": "D20", "59": "D20",
    **{f"{p:02d}": "D21" for p in range(60, 65)},
    **{f"{p:02d}": "D22" for p in range(65, 69)},
    **{f"{p:02d}": "D23" for p in range(69, 74)},
    "75": "D25", "76": "D25",
    "77": "D24", "78": "D24",
    "79": "D26", "80": "D26",
    "82": "D27", "83": "D27",
    "84": "D28", "85": "D28",
}
# D23 also covers 67
_POSTAL_PREFIX_TO_DISTRICT["67"] = "D23"


def postal_to_district(postal: str) -> str:
    """Map a 6-digit Singapore postal code to its planning district (e.g. 'D15')."""
    if not postal or len(postal) < 2:
        return ""
    return _POSTAL_PREFIX_TO_DISTRICT.get(postal[:2], "")


def _clean_address(address: str) -> str:
    """Strip PropertyGuru district annotations like '(D25-28)' before geocoding."""
    return re.sub(r"\s*\(D\d+[-–]?\d*\)", "", address).strip()


# Cache: search_val → (lat, lng, postal) or None
_cache: dict[str, tuple[float, float, str | None] | None] = {}


def geocode(
    address: str, postal_code: str | None
) -> tuple[float, float, str | None] | None:
    """Return (lat, lng, postal) for an address using OneMap Singapore API.

    postal is the 6-digit postal code returned by OneMap (may differ from the
    input postal_code if the input was absent or incorrect).
    """
    search_val = postal_code if postal_code else _clean_address(address)
    if not search_val:
        return None

    if search_val in _cache:
        return _cache[search_val]

    result = _query_onemap(search_val)
    if result is None and postal_code:
        cleaned = _clean_address(address)
        if cleaned and cleaned != search_val:
            result = _query_onemap(cleaned)

    _cache[search_val] = result
    return result


def _query_onemap(search_val: str) -> tuple[float, float, str | None] | None:
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
        postal = r.get("POSTAL") or None
        if postal and str(postal).upper() == "NIL":
            postal = None
        return lat, lng, str(postal) if postal else None
    except (ValueError, TypeError):
        return None
