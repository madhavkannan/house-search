import json
import logging
import re
import time
import random

import requests

from screener.config import (
    DISTRICTS, MAX_PRICE, MIN_BATHROOMS, MIN_BEDROOMS, MIN_SIZE_SQFT,
)
from screener.models import Listing
from screener.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

SQM_TO_SQFT = 10.7639
PAGE_SIZE = 25

# District "D09" → integer 9
DISTRICT_INTS = [int(d.lstrip("D")) for d in DISTRICTS]

# Try API versions in order until one works
_API_VERSIONS = ["v10", "v11", "v12", "v2"]
_NCO_BASE = "https://www.99.co"
# /singapore redirects (301) to / on the new Next.js App Router site
_NCO_SEARCH_PAGE = _NCO_BASE

# Candidate listing-search API paths to probe (all under /api/{version}/)
_LISTING_PATHS = [
    "web/listings/search",
    "listings/search",
    "web/search/listings",
    "search/listings",
    "web/listings",
    "listings",
    "web/properties/search",
]

# Candidate search page URLs — tried in order until one loads listing data
_SEARCH_PAGE_URLS = [
    f"{_NCO_BASE}/singapore/for-sale",
    f"{_NCO_BASE}/singapore/property-for-sale",
    f"{_NCO_BASE}/singapore/condos-apartments-for-sale",
    f"{_NCO_BASE}/singapore/sale",
    f"{_NCO_BASE}/buy",
    f"{_NCO_BASE}/singapore",
    _NCO_BASE,
]


def _html_has_listings(html: str) -> bool:
    """Quick check: does the HTML look like it contains listing data?"""
    # Property prices in SGD are 6+ digit numbers near "price" or "$"
    return bool(re.search(r'"price"\s*:\s*[1-9]\d{5,}', html))


def _extract_listings_from_html(html: str) -> list[dict]:
    """
    Extract listing dicts from Next.js-embedded page data.
    Tries __NEXT_DATA__ (Pages Router) first, then RSC payload scripts
    (App Router), then a generic large-JSON scan.
    """
    results: list[dict] = []

    # 1. __NEXT_DATA__ (Next.js Pages Router)
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            props = data.get("props", {}).get("pageProps", {})
            raw_listings = (
                props.get("listings")
                or (props.get("data") or {}).get("listings")
                or (props.get("searchResults") or {}).get("listings")
                or (props.get("result") or {}).get("listings")
                or []
            )
            if raw_listings:
                logger.info(f"[99co] __NEXT_DATA__ yielded {len(raw_listings)} listings")
                return raw_listings
            # Log available keys for diagnostics
            logger.info(f"[99co] __NEXT_DATA__ pageProps keys: {list(props.keys())[:15]}")
        except Exception as e:
            logger.info(f"[99co] __NEXT_DATA__ parse failed: {e}")

    # 2. Next.js App Router RSC payload: self.__next_f.push([1,"..."])
    # The payload encodes RSC chunks; look for embedded JSON objects with listing fields
    rsc_chunks: list[str] = []
    for m in re.finditer(r'self\.__next_f\.push\(\[.*?,"(.*?)"\]\)', html, re.S):
        rsc_chunks.append(m.group(1))

    if rsc_chunks:
        logger.info(f"[99co] Found {len(rsc_chunks)} RSC payload chunks")
        combined = "\n".join(rsc_chunks)
        # Un-escape JSON string escapes
        try:
            combined = combined.encode().decode("unicode_escape")
        except Exception:
            pass
        # Look for JSON arrays that contain listing-like objects
        results = _scan_for_listing_arrays(combined)
        if results:
            return results

    # 3. Generic scan: find JSON arrays with listing-shaped objects in all <script> tags
    for m in re.finditer(r'<script[^>]*>(.*?)</script>', html, re.S):
        chunk = m.group(1)
        if '"price"' not in chunk and '"bedrooms"' not in chunk:
            continue
        found = _scan_for_listing_arrays(chunk)
        if found:
            results.extend(found)

    return results


def _scan_for_listing_arrays(text: str) -> list[dict]:
    """Find JSON arrays whose items look like property listings."""
    results: list[dict] = []
    # Find positions of potential JSON arrays containing listing fields
    for m in re.finditer(r'\[(\s*\{[^{}]{0,50}"(?:price|bedrooms|listing_id|source_id)")', text):
        start = m.start()
        depth = 0
        for i, c in enumerate(text[start:], start):
            if c == '[':
                depth += 1
            elif c == ']':
                depth -= 1
                if depth == 0:
                    snippet = text[start:i + 1]
                    try:
                        arr = json.loads(snippet)
                        if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                            # Validate it's actually a listing array
                            if any(
                                k in arr[0]
                                for k in ("price", "bedrooms", "listing_id", "id", "url_path")
                            ):
                                logger.info(f"[99co] Found listing array: {len(arr)} items, keys={list(arr[0].keys())[:8]}")
                                results.extend(arr)
                    except Exception:
                        pass
                    break
    return results


def _normalize_district(raw: int | str | None) -> str:
    try:
        return f"D{int(raw):02d}"
    except (ValueError, TypeError):
        return ""


def _first_image(raw: dict) -> str | None:
    media = raw.get("media") or raw.get("photos") or []
    if isinstance(media, list) and media:
        item = media[0]
        if isinstance(item, dict):
            return item.get("url") or item.get("image_url")
        if isinstance(item, str):
            return item
    return None


class NinetyNineScraper(BaseScraper):
    SOURCE_NAME = "99co"

    def _api_params(self, page: int) -> dict:
        params = {
            "listing_type": "sale",
            "main_category": "residential",
            "sub_categories[]": ["condo", "apartment"],
            "price_max": MAX_PRICE,
            "bedrooms_min": MIN_BEDROOMS,
            "bathrooms_min": MIN_BATHROOMS,
            "floor_area_min": int(MIN_SIZE_SQFT / SQM_TO_SQFT),
            "floor_area_type": "sqm",
            "sort_by": "posted_at",
            "order": "desc",
            "page_size": PAGE_SIZE,
            "page_num": page,
        }
        params["districts[]"] = DISTRICT_INTS
        return params

    def _try_api(self, page: int) -> requests.Response | None:
        """Try each API version × path combination until one returns listings."""
        params = self._api_params(page)
        for version in _API_VERSIONS:
            for path in _LISTING_PATHS:
                url = f"{_NCO_BASE}/api/{version}/{path}"
                resp = self._get(
                    url,
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "Referer": _NCO_SEARCH_PAGE,
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    accept="application/json",
                    retries=1,
                )
                if resp is not None:
                    try:
                        body = resp.json()
                        # Accept any response that contains listing data
                        has_listings = (
                            (body.get("data") or {}).get("listings")
                            or body.get("listings")
                            or (body.get("result") or {}).get("listings")
                        )
                        if has_listings or body.get("status") == "success":
                            logger.info(f"[99co] API {version}/{path} responded OK")
                            return resp
                    except Exception:
                        pass
        return None

    def _scrape_via_api(self) -> list[Listing] | None:
        """Scrape via REST API. Returns None if API is unavailable."""
        listings: list[Listing] = []
        page = 1

        while True:
            resp = self._try_api(page)
            if resp is None:
                logger.warning("[99co] API unavailable on all versions — trying HTML")
                return None

            body = resp.json()
            data = body.get("data", {})
            raw_listings = data.get("listings", [])
            total = data.get("total", 0)

            if not raw_listings:
                logger.info(f"[99co] API page {page}: no listings — stopping")
                break

            for raw in raw_listings:
                try:
                    listings.append(self._parse_api(raw))
                except Exception as e:
                    logger.warning(f"[99co] Parse error: {e}")

            logger.info(f"[99co] API page {page}: {len(raw_listings)} listings (total={total})")

            if page * PAGE_SIZE >= total:
                break
            page += 1
            time.sleep(random.uniform(10, 20))

        return listings

    def _scrape_via_intercept(self) -> list[Listing]:
        """
        Load 99.co search pages in Playwright, intercept XHR responses AND
        parse SSR-embedded data (Next.js __NEXT_DATA__ or RSC payload).
        99.co migrated to Next.js App Router; listing data may be SSR-embedded
        rather than fetched via separate XHR.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("[99co] playwright not installed")
            return []

        from urllib.parse import urlparse

        captured: list[dict] = []
        total = 0
        discovered_api_url: list[str] = []
        html_pages: list[tuple[str, str]] = []  # (final_url, html)

        _PW_UA = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )

        def _handle_response(response):
            nonlocal total
            url = response.url
            ct = response.headers.get("content-type", "")
            if "99.co" in url or "99group" in url:
                logger.info(f"[99co-diag] {response.status} {ct[:40]} {url[:120]}")
            if not ("99.co" in url or "99group" in url):
                return
            if response.status != 200:
                return
            if "json" not in ct:
                return
            try:
                body = response.json()
                logger.info(f"[99co-diag] JSON keys: {list(body.keys())[:10]} from {url[:80]}")
                listings_found = (
                    (body.get("data") or {}).get("listings")
                    or body.get("listings")
                    or (body.get("result") or {}).get("listings")
                    or (body.get("data") or {}).get("data")
                    or []
                )
                if listings_found:
                    captured.extend(listings_found)
                    t = (
                        (body.get("data") or {}).get("total")
                        or body.get("total")
                        or 0
                    )
                    if t:
                        total = t
                    if not discovered_api_url:
                        parsed = urlparse(url)
                        discovered_api_url.append(
                            f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                        )
                    logger.info(
                        f"[99co] Intercepted {len(listings_found)} listings "
                        f"from {url[:100]}"
                    )
            except Exception as e:
                logger.info(f"[99co-diag] JSON parse failed for {url[:80]}: {e}")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage",
                          "--disable-blink-features=AutomationControlled"],
                )
                ctx = browser.new_context(
                    user_agent=_PW_UA,
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                )
                ctx.on("response", _handle_response)
                pg = ctx.new_page()
                pg.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
                )

                for search_url in _SEARCH_PAGE_URLS:
                    logger.info(f"[99co] Trying page: {search_url}")
                    try:
                        resp = pg.goto(search_url, wait_until="load", timeout=60_000)
                        final_url = pg.url
                        logger.info(f"[99co] Landed at: {final_url} (status={resp.status if resp else '?'})")
                        # Give dynamic content time to load
                        pg.wait_for_timeout(10_000)
                        html = pg.content()
                        html_pages.append((final_url, html))
                        if captured:
                            logger.info(f"[99co] XHR interception yielded {len(captured)} — stopping page loop")
                            break
                        # Check if HTML has listing data before trying next URL
                        if _html_has_listings(html):
                            logger.info(f"[99co] HTML contains listing data at {final_url}")
                            break
                    except Exception as e:
                        logger.warning(f"[99co] Failed to load {search_url}: {e}")
                        continue

                browser.close()
        except Exception as e:
            logger.error(f"[99co] Playwright intercept failed: {e}")
            return []

        logger.info(
            f"[99co] After page loads: {len(captured)} via XHR, "
            f"{len(html_pages)} HTML pages captured; "
            f"api_url={discovered_api_url[0] if discovered_api_url else 'none'}"
        )

        # Parse SSR-embedded listing data from HTML if XHR interception missed it
        if not captured and html_pages:
            for page_url, html in html_pages:
                extracted = _extract_listings_from_html(html)
                if extracted:
                    captured.extend(extracted)
                    logger.info(f"[99co] HTML extraction: {len(extracted)} listings from {page_url}")
                    break

        # Paginate via discovered API URL
        if discovered_api_url and total > PAGE_SIZE:
            api_url = discovered_api_url[0]
            logger.info(f"[99co] Paginating via discovered API: {api_url}")
            page = 2
            while page * PAGE_SIZE < total:
                resp = self._get(
                    api_url,
                    params=self._api_params(page),
                    headers={
                        "Accept": "application/json",
                        "Referer": _NCO_SEARCH_PAGE,
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    accept="application/json",
                    retries=2,
                )
                if resp is None:
                    logger.warning(f"[99co] Pagination failed at page {page}")
                    break
                try:
                    body = resp.json()
                    data = body.get("data", {})
                    raw_listings = (
                        data.get("listings")
                        or body.get("listings")
                        or (body.get("result") or {}).get("listings")
                        or []
                    )
                    if not raw_listings:
                        break
                    captured.extend(raw_listings)
                    logger.info(f"[99co] Paginated page {page}: {len(raw_listings)} listings")
                    page += 1
                    time.sleep(random.uniform(5, 10))
                except Exception as e:
                    logger.warning(f"[99co] Pagination parse error page {page}: {e}")
                    break

        listings: list[Listing] = []
        for raw in captured:
            try:
                listings.append(self._parse_api(raw))
            except Exception as e:
                logger.warning(f"[99co] Parse error: {e}")
        return listings

    def scrape(self) -> list[Listing]:
        result = self._scrape_via_api()
        if result is None:
            result = self._scrape_via_intercept()
        return result

    def _parse_api(self, raw: dict) -> Listing:
        attrs = raw.get("attributes") or raw.get("attr") or {}
        cluster = raw.get("cluster") or {}

        size_sqm = attrs.get("floor_area") or attrs.get("size_sqm")
        size_sqft: float | None = None
        if size_sqm:
            try:
                size_sqft = round(float(size_sqm) * SQM_TO_SQFT, 1)
            except (ValueError, TypeError):
                pass

        district_raw = raw.get("district") or cluster.get("district_code")
        district = _normalize_district(district_raw)

        url_path = raw.get("url_path") or raw.get("url") or ""
        if url_path and not url_path.startswith("http"):
            url_path = f"{_NCO_BASE}{url_path}"

        price_raw = raw.get("price") or raw.get("asking_price") or 0
        try:
            price = int(re.sub(r"[^\d]", "", str(price_raw))) if price_raw else 0
        except ValueError:
            price = 0

        address = (
            raw.get("address")
            or cluster.get("address_name")
            or raw.get("location")
            or ""
        )
        postal = raw.get("postal_code") or cluster.get("postal_code")

        return Listing(
            source="99co",
            source_id=str(raw.get("id") or ""),
            url=url_path,
            project_name=(
                raw.get("name")
                or cluster.get("name")
                or raw.get("project_name")
                or ""
            ),
            address=address,
            postal_code=str(postal) if postal else None,
            district=district,
            price=price,
            bedrooms=attrs.get("bedrooms") or raw.get("bedrooms"),
            bathrooms=attrs.get("bathrooms") or raw.get("bathrooms"),
            size_sqft=size_sqft,
            tenure=attrs.get("tenure") or raw.get("tenure"),
            image_url=_first_image(raw),
            description=raw.get("description"),
            listed_at=raw.get("posted_at") or raw.get("listing_date"),
        )

    def _parse_html_listing(self, raw: dict) -> Listing:
        """Parse a listing from 99.co __NEXT_DATA__ HTML structure."""
        # 99.co HTML listings may use different keys than the API
        size_sqm = raw.get("floor_area") or raw.get("size_sqm") or raw.get("area")
        size_sqft: float | None = None
        if size_sqm:
            try:
                v = float(size_sqm)
                size_sqft = round(v * SQM_TO_SQFT, 1) if v < 500 else v
            except (ValueError, TypeError):
                pass

        url_path = raw.get("url") or raw.get("url_path") or raw.get("listing_url") or ""
        if url_path and not url_path.startswith("http"):
            url_path = f"{_NCO_BASE}{url_path}"

        price_raw = raw.get("price") or raw.get("asking_price") or 0
        try:
            price = int(re.sub(r"[^\d]", "", str(price_raw))) if price_raw else 0
        except ValueError:
            price = 0

        district_raw = raw.get("district") or raw.get("district_code")
        district = _normalize_district(district_raw)

        return Listing(
            source="99co",
            source_id=str(raw.get("id") or raw.get("listing_id") or ""),
            url=url_path,
            project_name=raw.get("name") or raw.get("project_name") or "",
            address=raw.get("address") or raw.get("location") or "",
            postal_code=str(raw["postal_code"]) if raw.get("postal_code") else None,
            district=district,
            price=price,
            bedrooms=raw.get("bedrooms") or raw.get("bedroom"),
            bathrooms=raw.get("bathrooms") or raw.get("bathroom"),
            size_sqft=size_sqft,
            tenure=raw.get("tenure"),
            image_url=_first_image(raw),
            description=raw.get("description"),
            listed_at=raw.get("posted_at") or raw.get("listing_date"),
        )
