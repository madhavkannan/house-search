import re

from screener.models import Listing

_CONFIRMED = re.compile(
    r"\b(?:bomb\s+shelter|household\s+shelter|civil\s+defence\s+shelter"
    r"|internal\s+shelter|comes?\s+with\s+(?:a\s+)?shelter"
    r"|has\s+(?:a\s+)?shelter|with\s+(?:a\s+)?shelter|includes?\s+shelter"
    r")\b"
    r"|\bhs\b",
    re.IGNORECASE,
)

_ABSENT = re.compile(
    r"\b(?:no\s+(?:bomb\s+)?shelter|without\s+(?:bomb\s+)?shelter"
    r"|does\s+not\s+(?:come\s+with|have|include)\s+(?:a\s+)?(?:bomb\s+)?shelter"
    r"|no\s+hs"
    r")\b",
    re.IGNORECASE,
)


def detect_shelter(listing: Listing) -> str:
    """
    Returns "confirmed", "absent", or "unverified" based on listing description.
    Only "absent" results in exclusion — unverified listings are still shown.
    """
    text = listing.description or ""
    if not text.strip():
        return "unverified"

    if _ABSENT.search(text):
        return "absent"
    if _CONFIRMED.search(text):
        return "confirmed"
    return "unverified"
