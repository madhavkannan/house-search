from screener.config import (
    DISTRICTS, MAX_PRICE, MIN_BATHROOMS, MIN_BEDROOMS, MIN_SIZE_SQFT,
)
from screener.models import Listing


def passes_hard_criteria(listing: Listing) -> bool:
    """
    Return True to keep, False to exclude.
    Fields that are None are treated as unknown — lenient (kept) unless
    we KNOW they fail. Only shelter_status == "absent" is a hard exclude.
    """
    # Price: exclude if known and over budget, or zero (enquire-only)
    if listing.price == 0:
        return False
    if listing.price > MAX_PRICE:
        return False

    # District: must be in the target set
    if listing.district and listing.district not in DISTRICTS:
        return False

    # Bedrooms: exclude only if we know it's too few
    if listing.bedrooms is not None and listing.bedrooms < MIN_BEDROOMS:
        return False

    # Bathrooms: exclude only if we know it's too few
    if listing.bathrooms is not None and listing.bathrooms < MIN_BATHROOMS:
        return False

    # Size: exclude only if we know it's too small
    if listing.size_sqft is not None and listing.size_sqft < MIN_SIZE_SQFT:
        return False

    # Shelter: exclude only if explicitly confirmed absent
    if listing.shelter_status == "absent":
        return False

    return True
