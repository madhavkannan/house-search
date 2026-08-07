import logging
import random
import time
from abc import ABC, abstractmethod

import cloudscraper
import requests

from screener.config import USER_AGENTS
from screener.models import Listing

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    SOURCE_NAME: str = ""

    def __init__(self):
        self.session = cloudscraper.create_scraper(browser="chrome")
        self._rotate_headers()

    def _rotate_headers(self):
        self.session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
        })

    def _get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        retries: int = 3,
        accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    ) -> requests.Response | None:
        for attempt in range(retries):
            try:
                time.sleep(random.uniform(2, 5))
                self._rotate_headers()
                h = {"Accept": accept}
                if headers:
                    h.update(headers)
                resp = self.session.get(url, params=params, headers=h, timeout=30)
                if resp.status_code == 429:
                    wait = 30 * (attempt + 1)
                    logger.warning(f"[{self.SOURCE_NAME}] Rate-limited — waiting {wait}s")
                    time.sleep(wait)
                    continue
                if resp.status_code in (403, 503):
                    logger.warning(f"[{self.SOURCE_NAME}] HTTP {resp.status_code} on attempt {attempt + 1}")
                    time.sleep(10 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp
            except Exception as e:
                logger.warning(f"[{self.SOURCE_NAME}] Attempt {attempt + 1}/{retries} failed: {e}")
                time.sleep(5 * (attempt + 1))
        logger.error(f"[{self.SOURCE_NAME}] All retries exhausted for {url}")
        return None

    @abstractmethod
    def scrape(self) -> list[Listing]:
        ...
