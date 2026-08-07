import logging
import re
import time
import random

from screener.config import (
    DISTRICTS, MAX_PRICE, MIN_BATHROOMS, MIN_BEDROOMS, MIN_SIZE_SQFT,
    NCO_SEARCH_URL,
)
from screener.models import Listing
from screener.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

SQM_TO_SQFT = 10.7639
PAGE_SIZE = 25

# District string "D09" → integer 9
DISTRICT_INTS = [int(d.lstrip("D")) for d in DISTRICTS]


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

    def _base_params(self) -> dict:
        return {
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
        }

    def scrape(self) -> list[Listing]:
        listings: list[Listing] = []
        page = 1

        while True:
            params = {**self._base_params(), "page_num": page}
            # Repeat params for arrays (requests handles list values correctly)
            for d in DISTRICT_INTS:
                params.setdefault("districts[]", [])
                if isinstance(params["districts[]"], list):
                    params["districts[]"].append(d)
                else:
                    params["districts[]"] = [params["districts[]"], d]

            resp = self._get(
                NCO_SEARCH_URL,
                params=params,
                headers={
                    "Accept": "application/json",
                    "Referer": "https://www.99.co/singapore/condos-apartments-for-sale",
                    "X-Requested-With": "XMLHttpRequest",
                },
                accept="application/json",
            )
            if resp is None:
                logger.error("[99.co] Scrape aborted — no response")
                break

            try:
                body = resp.json()
            except Exception as e:
                logger.error(f"[99.co] JSON parse error: {e}")
                break

            if body.get("status") != "success" and not body.get("data"):
                logger.warning(f"[99.co] Unexpected response status: {body.get('status')}")
                break

            data = body.get("data", {})
            raw_listings = data.get("listings", [])
            total = data.get("total", 0)

            if not raw_listings:
                logger.info(f"[99.co] No listings on page {page} — stopping")
                break

            for raw in raw_listings:
                try:
                    listings.append(self._parse(raw))
                except Exception as e:
                    logger.warning(f"[99.co] Failed to parse listing: {e}")

            logger.info(f"[99.co] Page {page}: {len(raw_listings)} listings (total={total})")

            if page * PAGE_SIZE >= total:
                break
            page += 1
            time.sleep(random.uniform(10, 20))

        return listings

    def _parse(self, raw: dict) -> Listing:
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
            url_path = f"https://www.99.co{url_path}"

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
