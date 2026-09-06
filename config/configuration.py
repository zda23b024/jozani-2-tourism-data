import os
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote_plus


BASE_DIR = Path(__file__).resolve().parents[1]


def load_env_file() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(
            key.strip(),
            value.strip().strip('"').strip("'"),
        )


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, parsed)


def env_optional_int(name: str, default: int | None, minimum: int = 1) -> int | None:
    value = os.getenv(name)
    if value is None:
        return default
    if value.strip().lower() in {"", "none", "null", "all", "unlimited"}:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, parsed)


def env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip() or default


load_env_file()

BROWSER_DIR = BASE_DIR / "browser"
BOOKING_BROWSER_PROFILE_DIR = BROWSER_DIR / "booking_browser_profile"
BROWSER_PROFILE_DIR = BOOKING_BROWSER_PROFILE_DIR
TRIPADVISOR_BROWSER_PROFILE_DIR = BROWSER_DIR / "tripadvisor_browser_profile"

OUTPUT_DIR = BASE_DIR / "output"
CSV_DIR = OUTPUT_DIR / "csv"
JSON_DIR = OUTPUT_DIR / "json"
LOG_DIR = OUTPUT_DIR / "logs"
DEBUG_DIR = OUTPUT_DIR / "debug"
ATTRACTION_REVIEW_DEBUG_DIR = DEBUG_DIR / "attractions" / "reviews"

SEARCH_TERM = "Zanzibar"
SEARCH_COUNTRY = "Tanzania"
SEARCH_REGION = "Zanzibar"
SEARCH_ISLAND = "Unguja"
SEARCH_LOCATION_ID = "zanzibar_catalog"

STAYS_SEARCH_TERM = "Zanzibar"
STAYS_DEST_ID = 5140
STAYS_DEST_TYPE = "region"
STAYS_LANGUAGE = "en-us"
STAYS_AID = 1670475

CATALOG_SEARCH_TERMS = [
    STAYS_SEARCH_TERM,
]

ADULTS = 2
ROOMS = 1
CHILDREN = 0

ROWS_PER_PAGE = 25
ATTRACTIONS_PER_PAGE = 15
REVIEWS_PER_PAGE = 25

MAX_HOTEL_PAGES = None
MAX_CATALOG_HOTEL_PAGES = None
MAX_ATTRACTION_PAGES = None
MAX_REVIEW_PAGES_PER_HOTEL = None
MAX_REVIEW_PAGES_PER_ATTRACTION = env_optional_int("MAX_REVIEW_PAGES_PER_ATTRACTION", None)
BOOKING_ATTRACTION_REVIEW_PLACE_LIMIT = env_optional_int(
    "BOOKING_ATTRACTION_REVIEW_PLACE_LIMIT",
    None,
)

HEADLESS = env_bool("HEADLESS", False)
ALLOW_SCHEMA_REBUILD = env_bool("ALLOW_SCHEMA_REBUILD", False)
HOTEL_REVIEW_CONCURRENCY = env_int("HOTEL_REVIEW_CONCURRENCY", 1)
ATTRACTION_REVIEW_CONCURRENCY = env_int("ATTRACTION_REVIEW_CONCURRENCY", 1)
TRIPADVISOR_REVIEW_CONCURRENCY = env_int("TRIPADVISOR_REVIEW_CONCURRENCY", 1)

SEARCH_API_CAPTURE_TIMEOUT_SECONDS = 30
ATTRACTION_API_CAPTURE_TIMEOUT_SECONDS = 30

CHECKIN_DATE = date.today()
CHECKOUT_DATE = CHECKIN_DATE + timedelta(days=1)
CHECKIN = CHECKIN_DATE.isoformat()
CHECKOUT = CHECKOUT_DATE.isoformat()

SEARCH_URL = (
    f"https://www.booking.com/"
    f"searchresults.{STAYS_LANGUAGE}.html"
    f"?ss={quote_plus(STAYS_SEARCH_TERM)}"
    f"&ssne={quote_plus(STAYS_SEARCH_TERM)}"
    f"&ssne_untouched={quote_plus(STAYS_SEARCH_TERM)}"
    f"&aid={STAYS_AID}"
    f"&lang={STAYS_LANGUAGE}"
    f"&dest_id={STAYS_DEST_ID}"
    f"&dest_type={quote_plus(STAYS_DEST_TYPE)}"
    f"&checkin={CHECKIN}"
    f"&checkout={CHECKOUT}"
    f"&group_adults={ADULTS}"
    f"&no_rooms={ROOMS}"
    f"&group_children={CHILDREN}"
)

CATALOG_SEARCH_URL = (
    f"https://www.booking.com/"
    f"searchresults.{STAYS_LANGUAGE}.html"
    f"?ss={quote_plus(STAYS_SEARCH_TERM)}"
    f"&ssne={quote_plus(STAYS_SEARCH_TERM)}"
    f"&ssne_untouched={quote_plus(STAYS_SEARCH_TERM)}"
    f"&aid={STAYS_AID}"
    f"&lang={STAYS_LANGUAGE}"
    f"&dest_id={STAYS_DEST_ID}"
    f"&dest_type={quote_plus(STAYS_DEST_TYPE)}"
    f"&group_adults={ADULTS}"
    f"&no_rooms={ROOMS}"
    f"&group_children={CHILDREN}"
)

STAYS_GRAPHQL_URL = "https://www.booking.com/dml/graphql"
STAYS_GRAPHQL_OPERATION = "FullSearch"

ATTRACTIONS_DEST_ID = "-2574823"
ATTRACTIONS_UFI = -2574823
CATALOG_ATTRACTION_DESTINATIONS = [
    {
        "name": "Zanzibar",
        "dest_id": ATTRACTIONS_DEST_ID,
        "ufi": ATTRACTIONS_UFI,
    },
]

ATTRACTIONS_USE_DATES = False

ATTRACTIONS_AVAILABILITY_URL = (
    "https://www.booking.com/"
    "attractions/searchresults.en-us.html"
    "?selected_currency=TZS"
    "&source=search_box"
    f"&start_date={CHECKIN}"
    f"&end_date={CHECKOUT}"
    f"&dest_id={quote_plus(ATTRACTIONS_DEST_ID)}"
)

ATTRACTIONS_URL = (
    "https://www.booking.com/"
    "attractions/searchresults.en-us.html"
    "?selected_currency=TZS"
    "&source=search_box"
    f"&dest_id={quote_plus(ATTRACTIONS_DEST_ID)}"
)

CATALOG_ATTRACTIONS_URL = ATTRACTIONS_URL

ATTRACTIONS_GRAPHQL_URL = "https://accommodations.booking.com/dml/graphql"
ATTRACTIONS_GRAPHQL_OPERATION = "SearchResultsProducts"

COLLECT_ALL_STAYS = True
COLLECT_ALL_ATTRACTIONS = True
COLLECT_ALL_HOTEL_REVIEWS = True
COLLECT_ALL_ATTRACTION_REVIEWS = True

DEDUPLICATE_STAYS = True
DEDUPLICATE_ATTRACTIONS = True
DEDUPLICATE_REVIEWS = True

TRIPADVISOR_GEO_ID = env_str("TRIPADVISOR_GEO_ID", "482884")
TRIPADVISOR_LOCATION_SLUG = env_str(
    "TRIPADVISOR_LOCATION_SLUG",
    "Zanzibar_Island_Zanzibar_Archipelago",
)
MAX_TRIPADVISOR_HOTEL_PAGES = env_optional_int("MAX_TRIPADVISOR_HOTEL_PAGES", None)
MAX_TRIPADVISOR_PLACE_PAGES = env_optional_int("MAX_TRIPADVISOR_PLACE_PAGES", None)
MAX_TRIPADVISOR_REVIEW_PAGES = env_optional_int("MAX_TRIPADVISOR_REVIEW_PAGES", None)
TRIPADVISOR_REVIEW_PLACE_LIMIT = env_optional_int("TRIPADVISOR_REVIEW_PLACE_LIMIT", None)
TRIPADVISOR_RESULTS_PER_PAGE = env_int("TRIPADVISOR_RESULTS_PER_PAGE", 30)
TRIPADVISOR_REVIEWS_PER_PAGE = env_int("TRIPADVISOR_REVIEWS_PER_PAGE", 10)
TRIPADVISOR_RESTAURANT_REVIEWS_PER_PAGE = env_int(
    "TRIPADVISOR_RESTAURANT_REVIEWS_PER_PAGE",
    15,
)
TRIPADVISOR_CATALOG_TEST_FIRST_PAGE_ONLY = env_bool(
    "TRIPADVISOR_CATALOG_TEST_FIRST_PAGE_ONLY",
    False,
)
TRIPADVISOR_GRAPHQL_URL = env_str(
    "TRIPADVISOR_GRAPHQL_URL",
    "https://www.tripadvisor.com/data/graphql/ids",
)
TRIPADVISOR_HOTEL_REVIEWS_QUERY_ID = env_str(
    "TRIPADVISOR_HOTEL_REVIEWS_QUERY_ID",
    "ef3cb4f569f27e43",
)
TRIPADVISOR_REVIEW_GRAPHQL_ENABLED = env_bool(
    "TRIPADVISOR_REVIEW_GRAPHQL_ENABLED",
    True,
)
TRIPADVISOR_REVIEW_GRAPHQL_URL = env_str(
    "TRIPADVISOR_REVIEW_GRAPHQL_URL",
    TRIPADVISOR_GRAPHQL_URL,
)
TRIPADVISOR_REVIEW_GRAPHQL_QUERY_ID = env_str(
    "TRIPADVISOR_REVIEW_GRAPHQL_QUERY_ID",
    TRIPADVISOR_HOTEL_REVIEWS_QUERY_ID,
)
TRIPADVISOR_REVIEW_LANGUAGE = env_str("TRIPADVISOR_REVIEW_LANGUAGE", "en")
TRIPADVISOR_HOTEL_REVIEW_LANGUAGE_FILTER = env_str(
    "TRIPADVISOR_HOTEL_REVIEW_LANGUAGE_FILTER",
    "all",
)
TRIPADVISOR_REVIEW_PHOTOS_PER_REVIEW = env_int(
    "TRIPADVISOR_REVIEW_PHOTOS_PER_REVIEW",
    3,
)
TRIPADVISOR_HOTEL_GRAPHQL_ENABLED = env_bool("TRIPADVISOR_HOTEL_GRAPHQL_ENABLED", True)
TRIPADVISOR_HOTEL_GRAPHQL_URL = env_str(
    "TRIPADVISOR_HOTEL_GRAPHQL_URL",
    "https://www.tripadvisor.com/data/graphql/ids",
)
TRIPADVISOR_HOTEL_GRAPHQL_QUERY_ID = env_str(
    "TRIPADVISOR_HOTEL_GRAPHQL_QUERY_ID",
    "f101de74ce917363",
)
TRIPADVISOR_HOTEL_SORT = env_str("TRIPADVISOR_HOTEL_SORT", "BEST_VALUE")
TRIPADVISOR_HOTEL_PRICING_MODE = env_str(
    "TRIPADVISOR_HOTEL_PRICING_MODE",
    "ALL_IN_FULL_STAY",
)
TRIPADVISOR_ATTRACTIONS_GRAPHQL_ENABLED = env_bool(
    "TRIPADVISOR_ATTRACTIONS_GRAPHQL_ENABLED",
    True,
)
TRIPADVISOR_ATTRACTIONS_GRAPHQL_URL = env_str(
    "TRIPADVISOR_ATTRACTIONS_GRAPHQL_URL",
    "https://www.tripadvisor.com/data/graphql/ids",
)
TRIPADVISOR_ATTRACTIONS_GRAPHQL_QUERY_ID = env_str(
    "TRIPADVISOR_ATTRACTIONS_GRAPHQL_QUERY_ID",
    "ec9722f86b4550e3",
)
TRIPADVISOR_ATTRACTIONS_SORT = env_str(
    "TRIPADVISOR_ATTRACTIONS_SORT",
    "TRAVELER_RANKED",
)
TRIPADVISOR_RESTAURANTS_GRAPHQL_ENABLED = env_bool(
    "TRIPADVISOR_RESTAURANTS_GRAPHQL_ENABLED",
    True,
)
TRIPADVISOR_RESTAURANTS_GRAPHQL_URL = env_str(
    "TRIPADVISOR_RESTAURANTS_GRAPHQL_URL",
    "https://www.tripadvisor.com/data/graphql/ids",
)
TRIPADVISOR_RESTAURANTS_GRAPHQL_QUERY_ID = env_str(
    "TRIPADVISOR_RESTAURANTS_GRAPHQL_QUERY_ID",
    "7c7457de6bd4ad87",
)
TRIPADVISOR_RESTAURANTS_LOCALE = env_str(
    "TRIPADVISOR_RESTAURANTS_LOCALE",
    "en-US",
)

TRIPADVISOR_SEARCH_URL = (
    f"https://www.tripadvisor.com/Hotels-g{TRIPADVISOR_GEO_ID}-"
    f"a_ufe.true-{TRIPADVISOR_LOCATION_SLUG}-Hotels.html"
)
TRIPADVISOR_ATTRACTIONS_URL = (
    f"https://www.tripadvisor.com/Attractions-g{TRIPADVISOR_GEO_ID}-"
    f"Activities-a_allAttractions.true-{TRIPADVISOR_LOCATION_SLUG}.html"
)
TRIPADVISOR_RESTAURANTS_URL = (
    f"https://www.tripadvisor.com/Restaurants-g{TRIPADVISOR_GEO_ID}-"
    f"{TRIPADVISOR_LOCATION_SLUG}.html"
)
TRIPADVISOR_FIND_RESTAURANTS_URL = (
    f"https://www.tripadvisor.com/FindRestaurants?geo={TRIPADVISOR_GEO_ID}"
    "&broadened=false"
)


def ensure_project_dirs() -> None:
    for path in [
        BOOKING_BROWSER_PROFILE_DIR,
        TRIPADVISOR_BROWSER_PROFILE_DIR,
        CSV_DIR,
        JSON_DIR,
        LOG_DIR,
        DEBUG_DIR,
        ATTRACTION_REVIEW_DEBUG_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
