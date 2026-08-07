import os
from pathlib import Path

ROOT = Path(__file__).parent.parent

MAX_PRICE = 3_200_000
DISTRICTS = {"D02", "D09", "D11", "D14", "D15", "D16"}
MIN_BEDROOMS = 3
MIN_BATHROOMS = 3
MIN_SIZE_SQFT = 1_200.0
SCHOOL_KM = 1.0
MRT_WALK_M = 640  # ~8 min walk at 80 m/min

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

SCHOOLS_FILE = ROOT / "data" / "moe_primary_schools.json"
MRT_FILE = ROOT / "data" / "mrt_stations.json"

ONEMAP_SEARCH_URL = "https://www.onemap.gov.sg/api/common/elastic/search"

PG_SEARCH_URL = "https://www.propertyguru.com.sg/property-for-sale"
PG_PROPERTY_TYPES = ["CONDO", "APT"]

NCO_SEARCH_URL = "https://www.99.co/api/v10/web/listings/search"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]
