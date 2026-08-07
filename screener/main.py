import logging
import sys

from screener.db_writer import get_seen_ids, upsert_listing
from screener.deduplicator import deduplicate
from screener.filters import passes_hard_criteria
from screener.geocoder import geocode
from screener.models import Listing
from screener.mrt import mrt_within_walk
from screener.schools import schools_within_radius
from screener.scrapers.edgeprop import EdgePropScraper
from screener.scrapers.propertyguru import PropertyGuruScraper
from screener.shelter import detect_shelter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _enrich(listing: Listing, pg_scraper: PropertyGuruScraper) -> Listing:
    """Run all enrichment steps on a candidate listing in-place."""
    # 1. Shelter detection from description text
    listing.shelter_status = detect_shelter(listing)
    if listing.shelter_status == "absent":
        return listing  # Will be excluded downstream

    # 2. Fetch detail page if bathrooms still unknown (PropertyGuru only)
    if listing.bathrooms is None and listing.source in ("propertyguru",):
        listing = pg_scraper.fetch_detail(listing)

    # 3. Geocode
    coords = geocode(listing.address, listing.postal_code)
    if coords:
        listing.lat, listing.lng = coords
        listing.geocode_ok = True
        listing.nearby_schools = schools_within_radius(*coords)
        listing.nearby_mrt = mrt_within_walk(*coords)
    else:
        logger.warning(f"[main] Geocoding failed for '{listing.address}'")

    return listing


def main() -> None:
    logger.info("=== Singapore Condo Screener starting ===")

    # Step 1: Get already-seen listing IDs from Supabase
    seen_ids = get_seen_ids()
    logger.info(
        f"Seen: {len(seen_ids.get('propertyguru', set()))} PropertyGuru, "
        f"{len(seen_ids.get('edgeprop', set()))} EdgeProp"
    )

    # Step 2: Scrape both sources
    pg_scraper = PropertyGuruScraper()
    pg_listings = []
    try:
        pg_listings = pg_scraper.scrape()
    except Exception as e:
        logger.error(f"[main] PropertyGuru scraper crashed: {e}")

    ep_listings = []
    try:
        ep_listings = EdgePropScraper().scrape()
    except Exception as e:
        logger.error(f"[main] EdgeProp scraper crashed: {e}")

    all_listings = pg_listings + ep_listings
    logger.info(f"Scraped: {len(pg_listings)} PG + {len(ep_listings)} EdgeProp = {len(all_listings)} total")

    # Step 3: Deduplicate cross-source
    all_listings = deduplicate(all_listings)
    logger.info(f"After dedup: {len(all_listings)} unique listings")

    # Step 4: Hard-filter (price, district, beds, baths if known, size if known)
    candidates = [l for l in all_listings if passes_hard_criteria(l)]
    logger.info(f"After filter: {len(candidates)} candidates")

    # Step 5: Filter to new (unseen) listings only
    new_listings = [
        l for l in candidates
        if l.source_id not in seen_ids.get(l.source, set())
    ]
    logger.info(f"New (unseen): {len(new_listings)} listings")

    # Step 6: Enrich new candidates and upsert to Supabase
    saved = 0
    excluded = 0
    for listing in new_listings:
        listing = _enrich(listing, pg_scraper)

        # Re-check after enrichment (bathrooms now known, shelter confirmed absent)
        if not passes_hard_criteria(listing):
            excluded += 1
            logger.info(
                f"Excluded after enrichment: {listing.source}/{listing.source_id} "
                f"(shelter={listing.shelter_status}, baths={listing.bathrooms})"
            )
            continue

        if upsert_listing(listing):
            saved += 1
            logger.info(
                f"Saved: {listing.project_name or listing.source_id} "
                f"S${listing.price:,} {listing.district} "
                f"schools={len(listing.nearby_schools)} mrt={len(listing.nearby_mrt)}"
            )

    logger.info(
        f"=== Done: {saved} new listings saved, {excluded} excluded after enrichment ==="
    )


if __name__ == "__main__":
    main()
