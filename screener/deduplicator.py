import re

from screener.models import Listing

_STRIP = re.compile(r"[^\w\s]")
_COLLAPSE = re.compile(r"\s+")
_SUFFIXES = re.compile(
    r"\b(?:condo|condominium|apartment|residences?|residence|heights?|park|view|grove|gardens?)\b",
    re.IGNORECASE,
)


def _normalize_name(name: str) -> str:
    name = name.lower()
    name = _SUFFIXES.sub("", name)
    name = _STRIP.sub(" ", name)
    name = _COLLAPSE.sub(" ", name).strip()
    return name


def _price_key(price: int) -> int:
    """Round price to nearest 10k to allow ±1% tolerance."""
    return round(price / 10_000)


def _canonical_key(listing: Listing) -> tuple:
    if listing.postal_code:
        beds = listing.bedrooms or 0
        return ("postal", listing.postal_code, beds, _price_key(listing.price))
    name = _normalize_name(listing.project_name)
    return ("name", name, listing.district, _price_key(listing.price))


def _merge(a: Listing, b: Listing) -> Listing:
    """Keep the record with more non-None fields; prefer PropertyGuru on tie."""
    if a.completeness() >= b.completeness():
        winner, loser = a, b
    else:
        winner, loser = b, a

    # Fill nulls from the other record
    for attr in ("postal_code", "bedrooms", "bathrooms", "size_sqft",
                 "tenure", "image_url", "description", "listed_at"):
        if getattr(winner, attr) is None and getattr(loser, attr) is not None:
            setattr(winner, attr, getattr(loser, attr))
    return winner


def deduplicate(listings: list[Listing]) -> list[Listing]:
    seen: dict[tuple, Listing] = {}
    for listing in listings:
        key = _canonical_key(listing)
        if key in seen:
            seen[key] = _merge(seen[key], listing)
        else:
            seen[key] = listing
    return list(seen.values())
