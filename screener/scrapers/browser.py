"""
Page fetcher with three strategies, tried in order:
  1. ScrapingBee (residential IP, JS rendering) — preferred.
  2. curl_cffi Chrome impersonation — bypasses Cloudflare TLS checks without a proxy.
  3. Playwright headless Chromium — last resort.
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
    Strategy: ScrapingBee → curl_cffi Chrome impersonation → Playwright.
    """
    full_url = _build_url(url, params) if params else url

    if SCRAPINGBEE_API_KEY:
        result = _fetch_scrapingbee(full_url)
        if result is not None:
            return result
        logger.info("[browser] ScrapingBee unavailable — trying curl_cffi")

    result = _fetch_cffi(full_url)
    if result is not None:
        return result

    logger.info("[browser] curl_cffi failed — falling back to Playwright")
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
                    "block_resources": "false",  # ScrapingBee recommends false when hitting 500 errors
                    "wait": "8000",
                    "country_code": "sg",
                    "timeout": "30000",
                },
                timeout=120,  # premium_proxy + render_js can take 60-90s
            )
            if resp.status_code == 200:
                html = resp.text
                if "Just a moment" in html or "cf-browser-verification" in html:
                    logger.warning(
                        f"[scrapingbee] Cloudflare challenge page (attempt {attempt}/{retries}, {len(html):,} chars) — retrying"
                    )
                    if attempt < retries:
                        time.sleep(2 ** attempt)
                        continue
                    return None
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


def _fetch_cffi(url: str, retries: int = 2) -> str | None:
    """
    Fetch via curl_cffi impersonating Chrome — uses the real Chrome TLS fingerprint
    which clears Cloudflare's TLS JA3/JA4 checks without a residential proxy.
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        logger.warning("[cffi] curl_cffi not installed")
        return None

    for attempt in range(1, retries + 1):
        try:
            resp = cffi_requests.get(
                url,
                impersonate="chrome120",
                headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                timeout=30,
            )
            if resp.status_code == 200:
                html = resp.text
                if "Just a moment" in html or "cf-browser-verification" in html:
                    logger.warning(f"[cffi] Cloudflare JS challenge page (attempt {attempt}/{retries})")
                    if attempt < retries:
                        time.sleep(3)
                        continue
                    return None
                logger.info(f"[cffi] Fetched {len(html):,} chars from {url[:80]}")
                return html
            logger.warning(f"[cffi] HTTP {resp.status_code} (attempt {attempt}/{retries})")
            if attempt < retries:
                time.sleep(3)
        except Exception as e:
            logger.warning(f"[cffi] Request failed (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(3)
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
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--disable-extensions",
                    "--window-size=1920,1080",
                ],
            )
            ctx = browser.new_context(
                user_agent=_PW_UA,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="Asia/Singapore",
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                },
            )
            page = ctx.new_page()
            page.add_init_script("""
                Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
                Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
                Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});
                window.chrome={runtime:{}};
            """)
            page.goto(url, wait_until="load", timeout=timeout_ms)
            page.wait_for_timeout(4000)
            html = page.content()
            browser.close()
            if "Just a moment" in html or "cf-browser-verification" in html:
                logger.warning(f"[playwright] Cloudflare challenge page returned for {url[:80]}")
                return None
            logger.info(f"[playwright] Fetched {len(html):,} chars from {url[:80]}")
            return html
    except Exception as e:
        logger.error(f"[playwright] fetch failed: {e}")
        return None
