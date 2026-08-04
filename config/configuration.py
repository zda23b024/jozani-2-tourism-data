import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote_plus


BASE_DIR = Path(__file__).resolve().parents[1]
BROWSER_DIR = BASE_DIR / "browser"
BOOKING_BROWSER_PROFILE_DIR = BROWSER_DIR / "booking_browser_profile"
BROWSER_PROFILE_DIR = BOOKING_BROWSER_PROFILE_DIR
OUTPUT_DIR = BASE_DIR / "output"
CSV_DIR = OUTPUT_DIR / "csv"
JSON_DIR = OUTPUT_DIR / "json"
LOG_DIR = OUTPUT_DIR / "logs"

SEARCH_TERM = "Zanzibar City"
SEARCH_COUNTRY = "Tanzania"
SEARCH_REGION = "Zanzibar"
SEARCH_ISLAND = "Unguja"
SEARCH_LOCATION_ID = re.sub(r"[^a-z0-9]+", "_", SEARCH_TERM.lower()).strip("_")
ADULTS = 2
ROOMS = 1
CHILDREN = 0

ROWS_PER_PAGE = 25
ATTRACTIONS_PER_PAGE = 15
REVIEWS_PER_PAGE = 25
MAX_HOTEL_PAGES = 10
MAX_ATTRACTION_PAGES = 10
MAX_REVIEW_PAGES_PER_HOTEL = 10

HEADLESS = False

SEARCH_API_CAPTURE_TIMEOUT_SECONDS = 30
ATTRACTION_API_CAPTURE_TIMEOUT_SECONDS = 30

CHECKIN_DATE = date.today()
CHECKOUT_DATE = CHECKIN_DATE + timedelta(days=1)
CHECKIN = CHECKIN_DATE.isoformat()
CHECKOUT = CHECKOUT_DATE.isoformat()

SEARCH_URL = (
    "https://www.booking.com/searchresults.en-gb.html"
    f"?ss={quote_plus(SEARCH_TERM)}"
    f"&ssne={quote_plus(SEARCH_TERM)}"
    f"&ssne_untouched={quote_plus(SEARCH_TERM)}"
    f"&checkin={CHECKIN}"
    f"&checkout={CHECKOUT}"
    f"&group_adults={ADULTS}"
    f"&no_rooms={ROOMS}"
    f"&group_children={CHILDREN}"
    "&order=class"
)

ATTRACTIONS_DEST_ID = "-2574828"
ATTRACTIONS_URL = (
    "https://www.booking.com/attractions/searchresults.en-gb.html"
    "?selected_currency=TZS"
    "&source=search_box"
    f"&start_date={CHECKIN}"
    f"&end_date={CHECKOUT}"
    f"&dest_id={quote_plus(ATTRACTIONS_DEST_ID)}"
)


def ensure_project_dirs() -> None:
    for path in [
        BOOKING_BROWSER_PROFILE_DIR,
        CSV_DIR,
        JSON_DIR,
        LOG_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
