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


def _extract_district_from_address(text: str | None) -> str:
    """Extract district from strings like 'Katong (D15)' or 'North (D25-28)'."""
    if not text:
        return ""
    m = re.search(r"\(D(\d+)", text)
    if m:
        try:
            return f"D{int(m.group(1)):02d}"
        except ValueError:
            pass
    return ""


def _first_image(raw: dict) -> str | None:
    # New structure: mediaItems list of dicts
    for item in (raw.get("mediaItems") or []):
        if isinstance(item, dict):
            url = (
                item.get("url") or item.get("src") or item.get("origin")
                or item.get("cdnUrl") or item.get("thumbnailUrl")
                or item.get("thumbnail") or item.get("image")
            )
            if url and isinstance(url, str):
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
    params: dict = {
        "listing_type": "sale",
        "search": "true",
        "maxprice": MAX_PRICE,
        "minbeds": MIN_BEDROOMS,
        "minbaths": MIN_BATHROOMS,
        "minsize": int(MIN_SIZE_SQFT),
        "sort": "date",
        "order": "desc",
        "page": page,
        # Filter at URL level — reduces ScrapingBee credit burn on irrelevant pages
        "property_type_code[]": PG_PROPERTY_TYPES,
        "district_code[]": _district_codes(),
    }
    return params


def _extract_listings_from_obj(obj: object) -> list[dict]:
    """Recursively find the first list that looks like property listings."""
    if isinstance(obj, list) and obj:
        if isinstance(obj[0], dict) and any(
            k in obj[0] for k in ("id", "listingId", "price", "bedrooms", "url", "listingData")
        ):
            # Unwrap listingData wrapper if present
            if "listingData" in obj[0] and isinstance(obj[0]["listingData"], dict):
                return [item["listingData"] for item in obj if isinstance(item.get("listingData"), dict)]
            return [item for item in obj if isinstance(item, dict)]
    if isinstance(obj, dict):
        for key in ("listings", "listingsData", "results", "items", "data", "propertyListings"):
            val = obj.get(key)
            if val:
                result = _extract_listings_from_obj(val)
                if result:
                    return result
        for key, val in obj.items():
            if isinstance(val, (dict, list)):
                result = _extract_listings_from_obj(val)
                if result:
                    return result
    return []


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

        raw_listings: list[dict] = []
        total = 0

        # Path 1: pageData.data.listingsData[*].listingData (old structure)
        listings_wrappers = data_section.get("listingsData", [])
        if listings_wrappers:
            raw_listings = [
                item["listingData"]
                for item in listings_wrappers
                if isinstance(item.get("listingData"), dict)
            ]

        # Path 2: pageData.data.searchResultConfig — current structure (2025+)
        if not raw_listings:
            src = data_section.get("searchResultConfig")
            if isinstance(src, dict):
                logger.info(f"[PropertyGuru] searchResultConfig keys: {list(src.keys())[:20]}")
                raw_listings = _extract_listings_from_obj(src)
                total = src.get("total") or src.get("resultCount") or 0

        # Path 3: pageData.data.tabsViewData
        if not raw_listings:
            tvd = data_section.get("tabsViewData")
            if tvd:
                raw_listings = _extract_listings_from_obj(tvd)

        # Path 4: pageData.data.eligiblePropertiesData
        if not raw_listings:
            epd = data_section.get("eligiblePropertiesData")
            if epd:
                raw_listings = _extract_listings_from_obj(epd)

        # Path 5: pageProps.marketplace
        if not raw_listings:
            mp = page_props.get("marketplace")
            if mp:
                raw_listings = _extract_listings_from_obj(mp)
                if isinstance(mp, dict):
                    total = total or mp.get("total") or mp.get("resultCount") or 0

        # Path 6: legacy top-level pageProps keys
        if not raw_listings:
            raw_listings = (
                page_props.get("listings")
                or page_props.get("searchListingData", {}).get("listings", [])
                or []
            )
            if not isinstance(raw_listings, list):
                raw_listings = []

        if not total:
            total = (
                page_props.get("total")
                or (page_props.get("searchListingData") or {}).get("total", 0)
                or page_data.get("resultCount", 0)
                or len(raw_listings)
            )

        if not raw_listings:
            logger.warning(
                f"[PropertyGuru] No listings found — pageProps keys: {list(page_props.keys())[:20]}, "
                f"pageData keys: {list(page_data.keys())[:20] if isinstance(page_data, dict) else type(page_data).__name__}, "
                f"data keys: {list(data_section.keys())[:20] if data_section else 'empty'}"
            )
        else:
            logger.info(f"[PropertyGuru] Found {len(raw_listings)} raw listings, total={total}")

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
    listing_id = str(raw.get("id") or "")
    url_path = str(raw.get("url") or "")
    if url_path and not url_path.startswith("http"):
        url_path = f"https://www.propertyguru.com.sg{url_path}"
    if not url_path and listing_id:
        url_path = f"https://www.propertyguru.com.sg/property-for-sale/{listing_id}"

    # --- Price ---
    price_raw = raw.get("price")
    if isinstance(price_raw, dict):
        price_val = int(price_raw.get("value") or 0)
    elif isinstance(price_raw, str):
        price_val = int(re.sub(r"[^\d]", "", price_raw) or 0)
    else:
        price_val = int(price_raw or 0)

    # --- Beds/baths from top-level (most reliable) ---
    bedrooms: int | None = None
    bathrooms: int | None = None
    try:
        if raw.get("bedrooms") is not None:
            bedrooms = int(raw["bedrooms"])
    except (ValueError, TypeError):
        pass
    try:
        if raw.get("bathrooms") is not None:
            bathrooms = int(raw["bathrooms"])
    except (ValueError, TypeError):
        pass

    # --- listingFeatures: outer list is MIXED — first element is [list of icon dicts],
    #     remaining elements are plain dicts with dataAutomationId for size/tenure ---
    size_sqft: float | None = None
    tenure_raw: str | None = None
    for item in (raw.get("listingFeatures") or []):
        if isinstance(item, list):
            # Icon feature group — try to fill beds/baths if not already set
            for feat in item:
                if not isinstance(feat, dict):
                    continue
                icon = feat.get("iconName", "")
                text = str(feat.get("text") or "")
                if icon == "bed-o" and bedrooms is None:
                    try:
                        bedrooms = int(text)
                    except (ValueError, TypeError):
                        pass
                elif icon == "bath-o" and bathrooms is None:
                    try:
                        bathrooms = int(text)
                    except (ValueError, TypeError):
                        pass
        elif isinstance(item, dict):
            # Plain dict — contains area and tenure
            aid = item.get("dataAutomationId", "")
            text = str(item.get("text") or "")
            if (aid == "listing-card-v2-area" or "sqft" in text.lower()) and size_sqft is None:
                try:
                    v = float(re.sub(r"[^\d.]", "", text))
                    if v > 0:
                        size_sqft = round(v * 10.7639, 1) if v < 200 else v
                except (ValueError, TypeError):
                    pass
            elif aid == "listing-card-v2-tenure" and not tenure_raw:
                tenure_raw = text or None

    # Fallback size: top-level floorArea field
    if size_sqft is None and raw.get("floorArea") is not None:
        try:
            v = float(re.sub(r"[^\d.]", "", str(raw["floorArea"])))
            if v > 0:
                size_sqft = round(v * 10.7639, 1) if v < 200 else v
        except (ValueError, TypeError):
            pass

    # Last resort: derive from psfText + price
    if size_sqft is None and price_val:
        m = re.search(r"([\d,]+\.?\d*)\s*psf", (raw.get("psfText") or ""), re.IGNORECASE)
        if m:
            try:
                psf = float(m.group(1).replace(",", ""))
                if psf > 0:
                    size_sqft = round(price_val / psf, 1)
            except (ValueError, ZeroDivisionError):
                pass

    # --- Image: top-level thumbnail field ---
    thumbnail = raw.get("thumbnail")
    if isinstance(thumbnail, dict):
        image_url = (
            thumbnail.get("url") or thumbnail.get("src") or thumbnail.get("cdnUrl")
            or thumbnail.get("origin") or thumbnail.get("thumbnailUrl")
        )
    elif isinstance(thumbnail, str) and thumbnail:
        image_url = thumbnail
    else:
        image_url = _first_image(raw)

    # --- Address, project, district, postal ---
    full_address = str(raw.get("fullAddress") or raw.get("shortAddress") or "")
    project_name = str(raw.get("localizedTitle") or "")
    district = _extract_district_from_address(full_address)
    postal = _extract_postal(full_address)

    return Listing(
        source="propertyguru",
        source_id=listing_id,
        url=url_path,
        project_name=project_name,
        address=full_address,
        postal_code=str(postal) if postal else None,
        district=district,
        price=price_val,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        size_sqft=size_sqft,
        tenure=tenure_raw,
        image_url=image_url,
        description=str(raw.get("description") or "") or None,
        listed_at=raw.get("postedOn") or raw.get("listedAt"),
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
                    prop = raw.get("property") or {}
                    sub_type = prop.get("subTypeText") or prop.get("typeText") or ""
                    type_group = prop.get("typeGroup") or ""
                    # Skip HDB (H) and landed residential (L)
                    if type_group in ("H", "L") or sub_type in (
                        "HDB Flat", "Terrace House", "Terraced House",
                        "Semi-Detached House", "Bungalow", "Good Class Bungalow",
                        "Cluster House", "Corner Terrace", "Land Only", "Walk-up Apartment",
                    ):
                        continue
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
