"""Shared Playwright browser utility for Cloudflare-protected sites."""
import logging
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def fetch_html(url: str, params: dict | None = None, timeout_ms: int = 60_000) -> str | None:
    """
    Fetch a page using headless Chromium via Playwright.
    Returns raw HTML string, or None on failure.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("[browser] playwright not installed — cannot fetch")
        return None

    full_url = url
    if params:
        full_url = f"{url}?{urlencode(params, doseq=True)}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            ctx = browser.new_context(
                user_agent=_UA,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            page = ctx.new_page()
            # Patch navigator.webdriver to avoid bot detection
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page.goto(full_url, wait_until="networkidle", timeout=timeout_ms)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        logger.error(f"[browser] Playwright fetch failed for {full_url}: {e}")
        return None
