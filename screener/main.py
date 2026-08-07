import logging
import sys

from screener.db_writer import get_seen_ids, upsert_listing
from screener.deduplicator import deduplicate
from screener.filters import passes_hard_criteria
from screener.geocoder import geocode, postal_to_district
from screener.models import Listing
from screener.mrt import mrt_within_walk
from screener.schools import schools_within_radius
from screener.scrapers.propertyguru import PropertyGuruScraper
from screener.shelter import detect_shelter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _enrich(listing: Listing, pg_scraper: PropertyGuruScraper) -> Listing:
    # 1. Shelter detection from description text
    listing.shelter_status = detect_shelter(listing)
    if listing.shelter_status == "absent":
        return listing

    # 2. Fetch detail page if bathrooms still unknown
    if listing.bathrooms is None and listing.source == "propertyguru":
        listing = pg_scraper.fetch_detail(listing)

    # 3. Geocode + nearby schools/MRT
    geo = geocode(listing.address, listing.postal_code)
    if geo is None and listing.project_name:
        geo = geocode(listing.project_name, listing.postal_code)
    if geo:
        lat, lng, onemap_postal = geo
        listing.lat, listing.lng = lat, lng
        listing.geocode_ok = True
        # Backfill postal and district from OneMap if scraper couldn't determine them
        if onemap_postal and not listing.postal_code:
            listing.postal_code = onemap_postal
        if not listing.district:
            postal_for_district = listing.postal_code or onemap_postal
            if postal_for_district:
                listing.district = postal_to_district(postal_for_district)
        listing.nearby_schools = schools_within_radius(lat, lng)
        listing.nearby_mrt = mrt_within_walk(lat, lng)
    else:
        logger.warning(f"[main] Geocoding failed for '{listing.address}'")

    return listing


def main() -> None:
    logger.info("=== Singapore Condo Screener starting ===")

    seen_ids = get_seen_ids()
    logger.info(f"Seen: {len(seen_ids.get('propertyguru', set()))} PropertyGuru IDs in DB")

    pg_scraper = PropertyGuruScraper()
    pg_listings = []
    try:
        pg_listings = pg_scraper.scrape()
    except Exception as e:
        logger.error(f"[main] PropertyGuru scraper crashed: {e}", exc_info=True)

    all_listings = deduplicate(pg_listings)
    logger.info(f"Scraped: {len(pg_listings)} raw → {len(all_listings)} after dedup")

    candidates = [l for l in all_listings if passes_hard_criteria(l)]
    logger.info(f"After hard-filter: {len(candidates)} candidates")

    new_listings = [
        l for l in candidates
        if l.source_id not in seen_ids.get(l.source, set())
    ]
    logger.info(f"New (unseen): {len(new_listings)} listings to enrich")

    saved = 0
    excluded = 0
    for listing in new_listings:
        listing = _enrich(listing, pg_scraper)
        # Drop if we have no location signal at all — can't verify district
        if not listing.geocode_ok and not listing.district:
            excluded += 1
            logger.info(f"Excluded (no location): {listing.source_id} '{listing.address}'")
            continue
        if not passes_hard_criteria(listing):
            excluded += 1
            logger.info(
                f"Excluded post-enrich: {listing.source_id} "
                f"district={listing.district} shelter={listing.shelter_status} baths={listing.bathrooms}"
            )
            continue
        if upsert_listing(listing):
            saved += 1
            logger.info(
                f"Saved: {listing.project_name or listing.source_id} "
                f"S${listing.price:,} {listing.district} "
                f"schools={len(listing.nearby_schools)} mrt={len(listing.nearby_mrt)}"
            )

    logger.info(f"=== Done: {saved} saved, {excluded} excluded after enrichment ===")


if __name__ == "__main__":
    main()
