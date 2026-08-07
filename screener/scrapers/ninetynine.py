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
_NCO_SEARCH_PAGE = f"{_NCO_BASE}/singapore/condos-apartments-for-sale"


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
        """Try each API version until one returns 200."""
        params = self._api_params(page)
        for version in _API_VERSIONS:
            url = f"{_NCO_BASE}/api/{version}/web/listings/search"
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
                    if body.get("status") == "success" or body.get("data"):
                        logger.info(f"[99co] API {version} responded OK")
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
        Load 99.co in Playwright and intercept the XHR that fetches listings.
        99.co is client-side rendered — __NEXT_DATA__ has no listings, but the
        page fires an API call we can capture via response interception.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("[99co] playwright not installed")
            return []

        captured: list[dict] = []
        total = 0

        _PW_UA = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )

        search_url = (
            f"{_NCO_SEARCH_PAGE}"
            f"?listing_type=sale"
            f"&main_category=residential"
            f"&sub_categories[]=condo"
            f"&sub_categories[]=apartment"
            f"&price_max={MAX_PRICE}"
            f"&bedrooms_min={MIN_BEDROOMS}"
            f"&bathrooms_min={MIN_BATHROOMS}"
            f"&floor_area_min={int(MIN_SIZE_SQFT / SQM_TO_SQFT)}"
            f"&floor_area_type=sqm"
            f"&sort_by=posted_at&order=desc"
            + "".join(f"&districts[]={d}" for d in DISTRICT_INTS)
        )

        def _handle_response(response):
            nonlocal total
            url = response.url
            if not ("99.co" in url or "99group" in url):
                return
            if response.status != 200:
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            if not any(k in url for k in ("listing", "search", "property")):
                return
            try:
                body = response.json()
                listings_found = (
                    (body.get("data") or {}).get("listings")
                    or body.get("listings")
                    or (body.get("result") or {}).get("listings")
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
                    logger.info(
                        f"[99co] Intercepted {len(listings_found)} listings "
                        f"from {url[:100]}"
                    )
            except Exception:
                pass

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
                logger.info(f"[99co] Loading search page via Playwright intercept...")
                pg.goto(search_url, wait_until="load", timeout=90_000)
                pg.wait_for_timeout(8000)
                browser.close()
        except Exception as e:
            logger.error(f"[99co] Playwright intercept failed: {e}")
            return []

        logger.info(f"[99co] Intercepted total {len(captured)} listings (reported total={total})")
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
