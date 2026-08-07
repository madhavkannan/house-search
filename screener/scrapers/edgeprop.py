import json
import logging
import re
import time
import random

from bs4 import BeautifulSoup

from screener.config import (
    DISTRICTS, MAX_PRICE, MIN_BATHROOMS, MIN_BEDROOMS, MIN_SIZE_SQFT,
)
from screener.models import Listing
from screener.scrapers.browser import fetch_html

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.edgeprop.sg/for-sale"
PAGE_SIZE = 20
SQM_TO_SQFT = 10.7639

# EdgeProp uses district numbers directly
DISTRICT_NUMS = [int(d.lstrip("D")) for d in DISTRICTS]


def _normalize_district(raw) -> str:
    try:
        return f"D{int(raw):02d}"
    except (ValueError, TypeError):
        return ""


def _first_image(raw: dict) -> str | None:
    for key in ("photos", "images", "media", "photo"):
        items = raw.get(key) or []
        if isinstance(items, list) and items:
            item = items[0]
            if isinstance(item, dict):
                return item.get("url") or item.get("src") or item.get("image_url")
            if isinstance(item, str):
                return item
    return None


def _build_params(page: int) -> dict:
    return {
        "property_types[]": ["Condominium", "Apartment"],
        "min_bedroom": MIN_BEDROOMS,
        "min_bathroom": MIN_BATHROOMS,
        "max_price": MAX_PRICE,
        "min_floor_size": int(MIN_SIZE_SQFT),
        "districts[]": DISTRICT_NUMS,
        "page": page,
    }


class EdgePropScraper:
    SOURCE_NAME = "edgeprop"

    def scrape(self) -> list[Listing]:
        listings: list[Listing] = []
        page = 1

        while True:
            logger.info(f"[EdgeProp] Fetching page {page} via Playwright...")
            html = fetch_html(SEARCH_URL, params=_build_params(page))
            if html is None:
                logger.error("[EdgeProp] Scrape aborted — no response")
                break

            raw_listings, total = self._parse_html(html)

            if not raw_listings:
                logger.info(f"[EdgeProp] No listings on page {page} — stopping")
                break

            for raw in raw_listings:
                try:
                    listings.append(self._parse_listing(raw))
                except Exception as e:
                    logger.warning(f"[EdgeProp] Failed to parse listing: {e}")

            logger.info(f"[EdgeProp] Page {page}: {len(raw_listings)} listings (total={total})")

            if page * PAGE_SIZE >= total:
                break
            page += 1
            time.sleep(random.uniform(8, 15))

        return listings

    def _parse_html(self, html: str) -> tuple[list[dict], int]:
        soup = BeautifulSoup(html, "lxml")
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if not script_tag:
            logger.error("[EdgeProp] __NEXT_DATA__ not found in page")
            return [], 0
        try:
            data = json.loads(script_tag.string)
            page_props = data["props"]["pageProps"]
            # Try common paths in EdgeProp's data structure
            raw_listings = (
                page_props.get("listings")
                or page_props.get("data", {}).get("listings", [])
                or page_props.get("searchResults", {}).get("listings", [])
                or []
            )
            total = (
                page_props.get("total")
                or page_props.get("data", {}).get("total", 0)
                or page_props.get("searchResults", {}).get("total", 0)
                or 0
            )
            return raw_listings, total
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"[EdgeProp] JSON parse error: {e}")
            return [], 0

    def _parse_listing(self, raw: dict) -> Listing:
        size_raw = raw.get("floor_area") or raw.get("size") or raw.get("floor_area_sqft")
        size_sqft: float | None = None
        if size_raw:
            try:
                v = float(re.sub(r"[^\d.]", "", str(size_raw)))
                # heuristic: < 500 is sqm, convert
                size_sqft = round(v * SQM_TO_SQFT, 1) if v < 500 else v
            except ValueError:
                pass

        price_raw = raw.get("price") or raw.get("asking_price") or 0
        try:
            price = int(re.sub(r"[^\d]", "", str(price_raw))) if price_raw else 0
        except ValueError:
            price = 0

        district_raw = raw.get("district") or raw.get("district_code")
        district = _normalize_district(district_raw)

        url_path = raw.get("url") or raw.get("listing_url") or ""
        if url_path and not url_path.startswith("http"):
            url_path = f"https://www.edgeprop.sg{url_path}"

        return Listing(
            source="edgeprop",
            source_id=str(raw.get("id") or raw.get("listing_id") or ""),
            url=url_path,
            project_name=raw.get("project_name") or raw.get("name") or "",
            address=raw.get("address") or raw.get("street") or "",
            postal_code=str(raw["postal_code"]) if raw.get("postal_code") else None,
            district=district,
            price=price,
            bedrooms=raw.get("bedrooms") or raw.get("bedroom"),
            bathrooms=raw.get("bathrooms") or raw.get("bathroom"),
            size_sqft=size_sqft,
            tenure=raw.get("tenure"),
            image_url=_first_image(raw),
            description=raw.get("description"),
            listed_at=raw.get("listing_date") or raw.get("posted_at"),
        )
