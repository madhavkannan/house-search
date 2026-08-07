import json
import logging
import re
import time
import random

from bs4 import BeautifulSoup

from screener.config import (
    DISTRICTS, MAX_PRICE, MIN_BATHROOMS, MIN_BEDROOMS, MIN_SIZE_SQFT,
    PG_MAX_PAGES, PG_PROPERTY_TYPES, PG_SEARCH_URL,
)
from screener.models import Listing
from screener.scrapers.browser import fetch_html

logger = logging.getLogger(__name__)

PAGE_SIZE = 20


def _district_codes() -> list[str]:
    return [d.lstrip("D").lstrip("0") or "0" for d in DISTRICTS]


def _normalize_district(raw: str | None) -> str:
    if not raw:
        return ""
    raw = str(raw).strip().lstrip("D").lstrip("0")
    try:
        return f"D{int(raw):02d}"
    except ValueError:
        return ""


def _extract_postal(text: str | None) -> str | None:
    if not text:
        return None
    m = re.search(r"\b(\d{6})\b", text)
    return m.group(1) if m else None


def _first_image(raw: dict) -> str | None:
    photos = raw.get("photos") or raw.get("photo") or []
    if isinstance(photos, list) and photos:
        p = photos[0]
        if isinstance(p, dict):
            return p.get("url") or p.get("src")
        if isinstance(p, str):
            return p
    return None


def _build_params(page: int) -> dict:
    params: dict = {
        "listing_type": "sale",
        "search": "true",
        "maxprice": MAX_PRICE,
        "minbeds": MIN_BEDROOMS,
        "minbaths": MIN_BATHROOMS,
        "minsize": int(MIN_SIZE_SQFT),
        "freetext": "",
        "sort": "date",
        "order": "desc",
        "page": page,
    }
    for pt in PG_PROPERTY_TYPES:
        params.setdefault("property_type_code[]", []).append(pt)
    for dc in _district_codes():
        params.setdefault("district_code[]", []).append(dc)
    return params


def _parse_html(html: str) -> tuple[list[dict], int]:
    """Extract raw listing dicts and total count from page HTML."""
    soup = BeautifulSoup(html, "lxml")
    script_tag = soup.find("script", id="__NEXT_DATA__")
    if not script_tag:
        logger.error("[PropertyGuru] __NEXT_DATA__ not found in page")
        return [], 0
    try:
        data = json.loads(script_tag.string)
        page_props = data["props"]["pageProps"]
        raw_listings = (
            page_props.get("listings")
            or page_props.get("searchListingData", {}).get("listings", [])
            or []
        )
        total = (
            page_props.get("total")
            or page_props.get("searchListingData", {}).get("total", 0)
            or 0
        )
        return raw_listings, total
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"[PropertyGuru] JSON parse error: {e}")
        return [], 0


def _parse_listing(raw: dict) -> Listing:
    district = _normalize_district(
        raw.get("district") or raw.get("district_code")
    )
    price_val = raw.get("price") or raw.get("asking_price_formatted", "0")
    if isinstance(price_val, str):
        price_val = re.sub(r"[^\d]", "", price_val)
        price_val = int(price_val) if price_val else 0
    else:
        price_val = int(price_val or 0)

    size_raw = raw.get("floor_area_min") or raw.get("floor_area") or raw.get("size")
    size_sqft: float | None = None
    if size_raw:
        try:
            v = float(re.sub(r"[^\d.]", "", str(size_raw)))
            size_sqft = round(v * 10.7639, 1) if v < 200 else v
        except ValueError:
            pass

    listing_id = str(raw.get("id") or raw.get("listing_id") or "")
    url_path = raw.get("url") or raw.get("listing_url") or ""
    if url_path and not url_path.startswith("http"):
        url_path = f"https://www.propertyguru.com.sg{url_path}"

    address = raw.get("address") or raw.get("street_name") or raw.get("location") or ""
    postal = raw.get("postal_code") or _extract_postal(address)

    return Listing(
        source="propertyguru",
        source_id=listing_id,
        url=url_path,
        project_name=raw.get("name") or raw.get("project_name") or raw.get("listing_name") or "",
        address=address,
        postal_code=postal,
        district=district,
        price=price_val,
        bedrooms=raw.get("bedroom") or raw.get("bedrooms"),
        bathrooms=raw.get("bathroom") or raw.get("bathrooms"),
        size_sqft=size_sqft,
        tenure=raw.get("tenure"),
        image_url=_first_image(raw),
        description=raw.get("description"),
        listed_at=raw.get("listing_date") or raw.get("date_formatted"),
    )


class PropertyGuruScraper:
    SOURCE_NAME = "propertyguru"

    def scrape(self) -> list[Listing]:
        listings: list[Listing] = []
        page = 1

        while True:
            logger.info(f"[PropertyGuru] Fetching page {page}...")
            html = fetch_html(PG_SEARCH_URL, params=_build_params(page))
            if html is None:
                logger.error("[PropertyGuru] Scrape aborted — no response")
                break

            raw_listings, total = _parse_html(html)

            if not raw_listings:
                logger.info(f"[PropertyGuru] No listings on page {page} — stopping")
                break

            for raw in raw_listings:
                try:
                    listings.append(_parse_listing(raw))
                except Exception as e:
                    logger.warning(f"[PropertyGuru] Failed to parse listing: {e}")

            logger.info(f"[PropertyGuru] Page {page}: {len(raw_listings)} listings (total={total})")

            if page * PAGE_SIZE >= total or page >= PG_MAX_PAGES:
                break
            page += 1
            time.sleep(random.uniform(8, 15))

        return listings

    def fetch_detail(self, listing: Listing) -> Listing:
        """Fetch individual listing page to fill in missing bathrooms."""
        html = fetch_html(listing.url)
        if html is None:
            return listing
        soup = BeautifulSoup(html, "lxml")
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if not script_tag:
            return listing
        try:
            data = json.loads(script_tag.string)
            raw = data["props"]["pageProps"]["listing"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return listing

        if listing.bathrooms is None:
            listing.bathrooms = raw.get("bathroom") or raw.get("bathrooms")
        if listing.description is None:
            listing.description = raw.get("description", "")
        return listing
