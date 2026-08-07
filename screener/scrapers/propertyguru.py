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
    # New structure: mediaItems list of dicts
    for item in (raw.get("mediaItems") or []):
        if isinstance(item, dict):
            url = item.get("url") or item.get("src") or item.get("thumbnailUrl")
            if url:
                return url
        elif isinstance(item, str) and item:
            return item
    # Legacy fallback
    for key in ("photos", "photo"):
        for p in (raw.get(key) or []):
            if isinstance(p, dict):
                url = p.get("url") or p.get("src")
                if url:
                    return url
            elif isinstance(p, str) and p:
                return p
    return None


def _build_params(page: int) -> dict:
    # Omit array-style params (property_type_code[], district_code[]) — ScrapingBee rejects
    # URLs containing [] in parameter names. District/type filtering happens in passes_hard_criteria.
    return {
        "listing_type": "sale",
        "search": "true",
        "maxprice": MAX_PRICE,
        "minbeds": MIN_BEDROOMS,
        "minbaths": MIN_BATHROOMS,
        "minsize": int(MIN_SIZE_SQFT),
        "sort": "date",
        "order": "desc",
        "page": page,
    }


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
        page_data = page_props.get("pageData", {})
        data_section = page_data.get("data", {}) if isinstance(page_data.get("data"), dict) else {}

        # Primary path: pageData.data.listingsData[*].listingData
        listings_wrappers = data_section.get("listingsData", [])
        raw_listings = [
            item["listingData"]
            for item in listings_wrappers
            if isinstance(item.get("listingData"), dict)
        ]

        # Fallback paths for resilience
        if not raw_listings:
            raw_listings = (
                page_props.get("listings")
                or page_props.get("searchListingData", {}).get("listings", [])
                or []
            )

        total = (
            page_props.get("total")
            or page_props.get("searchListingData", {}).get("total", 0)
            or page_data.get("resultCount", 0)
            or len(raw_listings)
        )

        if raw_listings:
            logger.info(f"[PropertyGuru] listingData[0] keys: {list(raw_listings[0].keys())[:20]}")
            logger.info(f"[PropertyGuru] listingData[0] sample: {str(raw_listings[0])[:500]}")
        else:
            logger.warning("[PropertyGuru] No listings found in any known path")

        return raw_listings, total
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"[PropertyGuru] JSON parse error: {e}")
        return [], 0


def _scalar(v: object, *fallback_keys_in_dict: str) -> object:
    """If v is a dict, extract a scalar from it using common keys."""
    if not isinstance(v, dict):
        return v
    for k in fallback_keys_in_dict or ("value", "amount", "min", "text"):
        if v.get(k) is not None:
            return v[k]
    return None


def _parse_listing(raw: dict) -> Listing:
    # --- ID & URL ---
    listing_id = str(raw.get("id") or raw.get("listing_id") or raw.get("listingId") or "")
    url_path = str(raw.get("url") or raw.get("listing_url") or raw.get("listingUrl") or "")
    if url_path and not url_path.startswith("http"):
        url_path = f"https://www.propertyguru.com.sg{url_path}"
    if not url_path and listing_id:
        url_path = f"https://www.propertyguru.com.sg/property-for-sale/{listing_id}"

    # --- Price (may be a dict: {value, formatted, ...}) ---
    price_raw = raw.get("price")
    if isinstance(price_raw, dict):
        pv = price_raw.get("value") or price_raw.get("amount") or price_raw.get("min") or 0
        price_val = int(pv)
    elif isinstance(price_raw, str):
        cleaned = re.sub(r"[^\d]", "", price_raw)
        price_val = int(cleaned) if cleaned else 0
    else:
        price_val = int(price_raw or 0)

    # --- listingFeatures: [[{iconName, text}, ...], ...] ---
    bedrooms: int | None = None
    bathrooms: int | None = None
    size_from_features: float | None = None
    for group in (raw.get("listingFeatures") or []):
        if not isinstance(group, list):
            continue
        for feat in group:
            if not isinstance(feat, dict):
                continue
            icon = feat.get("iconName", "")
            text = str(feat.get("text") or "")
            if icon == "bed-o":
                try:
                    bedrooms = int(text)
                except (ValueError, TypeError):
                    pass
            elif icon == "bath-o":
                try:
                    bathrooms = int(text)
                except (ValueError, TypeError):
                    pass
            elif icon in ("area-o", "area", "size") or "sqft" in text.lower() or "sqm" in text.lower():
                try:
                    v = float(re.sub(r"[^\d.]", "", text))
                    if v > 0:
                        size_from_features = round(v * 10.7639, 1) if v < 200 else v
                except (ValueError, TypeError):
                    pass

    # --- property sub-dict: district, postal, tenure, description, size ---
    prop = raw.get("property") or {}

    district = _normalize_district(
        prop.get("district") or prop.get("districtCode") or prop.get("district_code")
        or raw.get("district") or raw.get("district_code")
    )

    postal = (
        prop.get("postalCode") or prop.get("postal_code")
        or raw.get("postalCode") or raw.get("postal_code")
        or _extract_postal(raw.get("fullAddress") or raw.get("shortAddress"))
    )

    tenure_raw = prop.get("tenure") or prop.get("tenureText") or raw.get("tenure")

    description = str(prop.get("description") or raw.get("description") or "") or None

    # Size: prefer features parse, fall back to property dict
    size_sqft: float | None = size_from_features
    if size_sqft is None:
        size_raw = (
            prop.get("floorAreaMin") or prop.get("floor_area_min")
            or prop.get("floorArea") or prop.get("size")
        )
        if size_raw:
            try:
                v = float(re.sub(r"[^\d.]", "", str(size_raw)))
                if v > 0:
                    size_sqft = round(v * 10.7639, 1) if v < 200 else v
            except (ValueError, TypeError):
                pass

    # --- Address & project name ---
    address = str(
        raw.get("fullAddress") or raw.get("shortAddress")
        or prop.get("address") or raw.get("address") or ""
    )
    project_name = str(
        raw.get("localizedTitle") or prop.get("projectName") or prop.get("name")
        or raw.get("project_name") or raw.get("listingName") or ""
    )

    return Listing(
        source="propertyguru",
        source_id=listing_id,
        url=url_path,
        project_name=project_name,
        address=address,
        postal_code=str(postal) if postal else None,
        district=district,
        price=price_val,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        size_sqft=size_sqft,
        tenure=str(tenure_raw) if tenure_raw else None,
        image_url=_first_image(raw),
        description=description,
        listed_at=raw.get("listing_date") or raw.get("date_formatted") or raw.get("listedAt"),
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
