"""
Page fetcher with two strategies:
  1. ScrapingBee (residential IP, JS rendering) — preferred; used when SCRAPINGBEE_API_KEY is set.
  2. Playwright headless Chromium — fallback for non-Cloudflare sites.
"""
import logging
import os
import time
from urllib.parse import quote, urlencode

import requests as _requests

logger = logging.getLogger(__name__)

SCRAPINGBEE_API_KEY = os.environ.get("SCRAPINGBEE_API_KEY", "")
SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"

_PW_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def _build_url(base: str, params: dict) -> str:
    # urlencode encodes [] as %5B%5D — ScrapingBee rejects URLs with percent-encoded brackets.
    # Keep literal [] so array-style params reach PropertyGuru correctly.
    qs = urlencode(params, doseq=True, quote_via=quote).replace("%5B%5D", "[]")
    return f"{base}?{qs}"


def fetch_html(url: str, params: dict | None = None, timeout_ms: int = 90_000) -> str | None:
    """
    Fetch a page and return its rendered HTML.
    Tries ScrapingBee first (when API key present), falls back to Playwright.
    """
    full_url = _build_url(url, params) if params else url

    if SCRAPINGBEE_API_KEY:
        return _fetch_scrapingbee(full_url)
    return _fetch_playwright(full_url, timeout_ms)


def _fetch_scrapingbee(url: str, retries: int = 3) -> str | None:
    """
    Fetch via ScrapingBee API — residential IPs, JS rendering for Cloudflare bypass.
    Free tier: 1000 credits/month. render_js=true costs 5 credits/request.
    HTTP 500 from ScrapingBee means their server errored (not charged) — retries are safe.
    """
    for attempt in range(1, retries + 1):
        try:
            resp = _requests.get(
                SCRAPINGBEE_URL,
                params={
                    "api_key": SCRAPINGBEE_API_KEY,
                    "url": url,
                    "render_js": "true",
                    "premium_proxy": "true",   # needed for Cloudflare Bot Management; costs 25 credits/req
                    "wait": "4000",
                    "country_code": "sg",
                    "timeout": "30000",
                },
                timeout=60,
            )
            if resp.status_code == 200:
                html = resp.text
                if "Just a moment" in html or "cf-browser-verification" in html:
                    logger.warning("[scrapingbee] Cloudflare challenge page returned")
                logger.info(f"[scrapingbee] Fetched {len(html):,} chars from {url[:80]}")
                return html
            if resp.status_code == 500:
                logger.warning(
                    f"[scrapingbee] HTTP 500 (attempt {attempt}/{retries}): {resp.text[:200]}"
                )
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    continue
            else:
                logger.error(f"[scrapingbee] HTTP {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            logger.error(f"[scrapingbee] Request failed (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
    return None


def _fetch_playwright(url: str, timeout_ms: int) -> str | None:
    """Fallback: headless Chromium via Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("[playwright] not installed")
        return None

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
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            page = ctx.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            page.goto(url, wait_until="load", timeout=timeout_ms)
            page.wait_for_timeout(5000)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        logger.error(f"[playwright] fetch failed: {e}")
        return None
