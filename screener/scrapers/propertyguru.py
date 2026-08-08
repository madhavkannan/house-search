import json
import logging
import re
import time
import random
from urllib.parse import quote, urlencode

from bs4 import BeautifulSoup

from screener.config import (
    DISTRICTS, MAX_PRICE, MIN_BATHROOMS, MIN_BEDROOMS, MIN_SIZE_SQFT,
    PG_MAX_PAGES, PG_PROPERTY_TYPES, PG_SEARCH_URL,
)
from screener.models import Listing
from screener.scrapers.browser import fetch_html, fetch_json_intercept

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


def _extract_build_id(html: str) -> str | None:
    """Extract Next.js buildId from __NEXT_DATA__ — needed for /_next/data API."""
    try:
        soup = BeautifulSoup(html, "lxml")
        tag = soup.find("script", id="__NEXT_DATA__")
        if tag:
            data = json.loads(tag.string)
            return data.get("buildId")
    except Exception:
        pass
    return None


def _fetch_nextdata_api(build_id: str, page: int) -> tuple[list[dict], int]:
    """
    Fetch via Next.js /_next/data/{buildId}/property-for-sale.json endpoint.
    This is PG's internal prefetch API — pure JSON, no JS rendering required,
    which may bypass bot detection that targets the HTML page.
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        logger.warning("[nextdata] curl_cffi not installed")
        return [], 0

    params = _build_params(page)
    qs = urlencode(params, doseq=True, quote_via=quote).replace("%5B%5D", "[]")
    next_url = f"https://www.propertyguru.com.sg/_next/data/{build_id}/property-for-sale.json?{qs}"
    logger.info(f"[nextdata] Trying: {next_url[:200]}")

    for attempt in range(1, 4):
        try:
            resp = cffi_requests.get(
                next_url,
                impersonate="chrome120",
                headers={
                    "Accept": "application/json, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.propertyguru.com.sg/property-for-sale",
                    "x-nextjs-data": "1",
                },
                timeout=30,
            )
            logger.info(f"[nextdata] HTTP {resp.status_code} (attempt {attempt})")
            if resp.status_code == 200:
                data = resp.json()
                page_props = data.get("pageProps", {})
                page_data = page_props.get("pageData", {})
                data_section = (
                    page_data.get("data", {})
                    if isinstance(page_data.get("data"), dict) else {}
                )
                result_count = page_data.get("resultCount") if isinstance(page_data, dict) else None
                search_params = page_data.get("searchParams") if isinstance(page_data, dict) else None
                logger.info(
                    f"[nextdata] resultCount={result_count}, "
                    f"pageData keys: {list(page_data.keys())[:20] if isinstance(page_data, dict) else 'N/A'}, "
                    f"data keys: {list(data_section.keys())[:20] if data_section else 'empty'}"
                )
                if search_params:
                    logger.info(f"[nextdata] searchParams: {json.dumps(search_params)[:600]}")
                raw_listings = _find_all_listing_dicts(data)
                total = result_count or len(raw_listings)
                if raw_listings:
                    logger.info(f"[nextdata] Found {len(raw_listings)} listings, total={total}")
                else:
                    logger.warning(f"[nextdata] 0 listings — full pageData: {json.dumps(page_data)[:1000]}")
                return raw_listings, total
            elif resp.status_code in (404, 410):
                logger.warning(f"[nextdata] {resp.status_code} — buildId may be stale")
                return [], 0
            elif attempt < 3:
                time.sleep(2 ** attempt)
        except Exception as e:
            logger.warning(f"[nextdata] Failed (attempt {attempt}): {e}")
            if attempt < 3:
                time.sleep(2 ** attempt)
    return [], 0


def _find_all_listing_dicts(obj: object, depth: int = 0) -> list[dict]:
    """
    Walk the entire JSON tree and collect every dict that looks like a property listing.
    Matches on price > 100k (as int or nested dict) + any of bedrooms/id/url.
    """
    if depth > 25:
        return []
    results: list[dict] = []
    if isinstance(obj, dict):
        price = obj.get("price")
        price_val = (
            price if isinstance(price, (int, float))
            else price.get("value") if isinstance(price, dict)
            else None
        )
        if price_val and price_val > 100_000 and any(
            k in obj for k in ("bedrooms", "bathrooms", "id", "url", "address", "localizedTitle")
        ):
            results.append(obj)
        else:
            for val in obj.values():
                if isinstance(val, (dict, list)):
                    results.extend(_find_all_listing_dicts(val, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                results.extend(_find_all_listing_dicts(item, depth + 1))
    return results


def _parse_html(html: str) -> tuple[list[dict], int]:
    """Extract raw listing dicts and total count from page HTML."""
    soup = BeautifulSoup(html, "lxml")
    script_tag = soup.find("script", id="__NEXT_DATA__")
    if not script_tag:
        logger.error("[PropertyGuru] __NEXT_DATA__ not found in page")
        # Last-resort: count price-like patterns in raw HTML to confirm data is present
        price_hits = len(re.findall(r'"price"\s*:\s*[1-9]\d{5,}', html))
        logger.error(f"[PropertyGuru] Raw HTML price-pattern hits: {price_hits}")
        return [], 0
    try:
        data = json.loads(script_tag.string)
        page_props = data["props"]["pageProps"]
        page_data = page_props.get("pageData", {})
        data_section = page_data.get("data", {}) if isinstance(page_data.get("data"), dict) else {}

        result_count_ssr = page_data.get("resultCount") if isinstance(page_data, dict) else None
        rbls = page_data.get("rblsRequestParams") if isinstance(page_data, dict) else None
        search_params_ssr = page_data.get("searchParams") if isinstance(page_data, dict) else None
        logger.info(
            f"[PropertyGuru] pageProps keys: {list(page_props.keys())[:25]}, "
            f"pageData keys: {list(page_data.keys())[:25] if isinstance(page_data, dict) else type(page_data).__name__}, "
            f"data keys: {list(data_section.keys())[:25] if data_section else 'empty'}, "
            f"resultCount={result_count_ssr}"
        )
        if rbls:
            logger.info(f"[PropertyGuru] rblsRequestParams: {json.dumps(rbls)[:600]}")
        if search_params_ssr:
            logger.info(f"[PropertyGuru] searchParams: {json.dumps(search_params_ssr)[:600]}")
        else:
            logger.info(f"[PropertyGuru] searchParams: absent — full pageData snippet: {json.dumps(page_data)[:1500] if isinstance(page_data, dict) else str(page_data)[:500]}")

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
            logger.info(f"[PropertyGuru] Path1 (listingsData): {len(raw_listings)} listings")

        # Path 2: walk the entire data_section tree for any dict with price+listing keys
        if not raw_listings and data_section:
            raw_listings = _find_all_listing_dicts(data_section)
            if raw_listings:
                logger.info(f"[PropertyGuru] Path2 (tree-walk data_section): {len(raw_listings)} listings")

        # Path 3: walk pageProps (excluding pageData to avoid re-scan)
        if not raw_listings:
            pp_without_pagedata = {k: v for k, v in page_props.items() if k != "pageData"}
            raw_listings = _find_all_listing_dicts(pp_without_pagedata)
            if raw_listings:
                logger.info(f"[PropertyGuru] Path3 (tree-walk pageProps): {len(raw_listings)} listings")

        # Path 4: walk the entire __NEXT_DATA__ tree as absolute last resort
        if not raw_listings:
            raw_listings = _find_all_listing_dicts(data)
            if raw_listings:
                logger.info(f"[PropertyGuru] Path4 (tree-walk full NEXT_DATA): {len(raw_listings)} listings")

        # Extract total from known locations
        if data_section:
            for key in ("total", "resultCount", "totalCount", "listingCount"):
                val = data_section.get(key)
                if isinstance(val, int) and val > 0:
                    total = val
                    break
        if not total:
            total = (
                page_props.get("total")
                or (page_props.get("searchListingData") or {}).get("total", 0)
                or page_data.get("resultCount", 0)
                or len(raw_listings)
            )

        # Path 5: JSON-LD structured data (<script type="application/ld+json">)
        # PG embeds schema.org markup for SEO which may contain listing info
        if not raw_listings:
            for ld_tag in soup.find_all("script", type="application/ld+json"):
                try:
                    ld = json.loads(ld_tag.string or "")
                    found = _find_all_listing_dicts(ld)
                    if found:
                        raw_listings.extend(found)
                        logger.info(f"[PropertyGuru] Path5 (JSON-LD): {len(found)} listings")
                except (json.JSONDecodeError, TypeError):
                    pass

        if not raw_listings:
            # Diagnostic: scan raw HTML for price patterns to confirm data is present
            price_hits = len(re.findall(r'"price"\s*:\s*[1-9]\d{5,}', html))
            # Also scan for schema.org price patterns
            price_hits2 = len(re.findall(r'"salePrice"|"priceSpecification"|"offers"', html))
            logger.warning(
                f"[PropertyGuru] No listings found — raw HTML price-pattern hits: {price_hits}, "
                f"schema-price hits: {price_hits2}, "
                f"__NEXT_DATA__ size: {len(script_tag.string):,} chars"
            )
            # Log tabsViewData / eligiblePropertiesData structure for diagnosis
            for diag_key in ("tabsViewData", "eligiblePropertiesData", "searchResultConfig", "recommendationsConfig"):
                val = data_section.get(diag_key)
                if val is not None:
                    if isinstance(val, dict):
                        logger.info(f"[PropertyGuru] {diag_key} keys: {list(val.keys())[:20]}")
                    elif isinstance(val, list):
                        logger.info(f"[PropertyGuru] {diag_key} list len={len(val)}, first item type: {type(val[0]).__name__ if val else 'empty'}")
        else:
            logger.info(f"[PropertyGuru] Found {len(raw_listings)} raw listings, total={total}")

        return raw_listings, total
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"[PropertyGuru] JSON parse error: {e}")
        return [], 0


def _find_listings_in_json_responses(responses: list[dict]) -> tuple[list[dict], int]:
    """Search all intercepted JSON API responses for listing dicts."""
    all_listings: list[dict] = []
    total = 0

    for resp in responses:
        resp_url = resp.get("url", "")
        data = resp.get("data")
        if not data:
            continue
        found = _find_all_listing_dicts(data)
        if found:
            logger.info(f"[PropertyGuru] Intercept found {len(found)} listings in: {resp_url[:100]}")
            all_listings.extend(found)
            if isinstance(data, dict):
                for key in ("total", "resultCount", "totalCount", "listingCount", "count"):
                    val = data.get(key)
                    if isinstance(val, int) and val > total:
                        total = val
        else:
            # Log all JSON URLs that returned nothing so we can diagnose
            logger.debug(f"[PropertyGuru] Intercept no-listings from: {resp_url[:100]}")

    if not all_listings:
        logger.warning(
            f"[PropertyGuru] Intercept found 0 listings across {len(responses)} JSON responses. "
            f"URLs: {[r['url'][:80] for r in responses[:10]]}"
        )

    return all_listings, total or len(all_listings)


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
        build_id: str | None = None  # cached for _next/data API fallback

        while True:
            logger.info(f"[PropertyGuru] Fetching page {page}...")
            html = fetch_html(PG_SEARCH_URL, params=_build_params(page))

            raw_listings: list[dict] = []
            total = 0

            if html is not None:
                raw_listings, total = _parse_html(html)
                # Extract buildId once (page 1) for _next/data API fallback
                if build_id is None:
                    build_id = _extract_build_id(html)
                    if build_id:
                        logger.info(f"[PropertyGuru] buildId: {build_id}")
            else:
                logger.warning("[PropertyGuru] fetch_html returned None — skipping SSR parse, trying fallbacks")

            # Fallback 1: Next.js /_next/data JSON API — bypasses HTML page bot detection
            if not raw_listings and build_id:
                logger.info(f"[PropertyGuru] SSR empty on page {page} — trying _next/data API (buildId={build_id})")
                raw_listings, total = _fetch_nextdata_api(build_id, page)

            # Fallback 2: Playwright response interception
            if not raw_listings:
                logger.info(f"[PropertyGuru] _next/data empty on page {page} — trying Playwright intercept")
                json_responses = fetch_json_intercept(
                    PG_SEARCH_URL, params=_build_params(page), wait_ms=15000
                )
                raw_listings, total = _find_listings_in_json_responses(json_responses)

            if not raw_listings:
                if html is None and build_id is None:
                    logger.error("[PropertyGuru] Scrape aborted — fetch_html failed and no buildId for _next/data")
                else:
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
