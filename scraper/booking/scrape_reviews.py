import html
import json
import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote_plus

from playwright.async_api import BrowserContext, Page, Request

from config.configuration import (
    CHECKIN,
    CHECKOUT,
    MAX_REVIEW_PAGES_PER_HOTEL,
    REVIEWS_PER_PAGE,
)
from utils.browser_helpers import (
    accept_cookies,
    build_fetch_headers,
    fetch_graphql_page,
    parse_request_body,
)
from utils.helpers import (
    first_nonempty,
    hotel_stay_url,
    nested_get,
    stable_review_id,
    translation_text,
    parse_date,
)


def review_cutoff_date() -> date | None:
    checkin = parse_date(CHECKIN)
    checkout = parse_date(CHECKOUT)
    today = date.today()
    if checkin == today and checkout == today + timedelta(days=1):
        return today - timedelta(days=1)
    return None


def normalize_increment_state(state: Any) -> dict[str, Any]:
    if isinstance(state, set):
        return {
            "source_review_ids": state,
            "newest_review_date": None,
        }
    if isinstance(state, dict):
        return {
            "source_review_ids": set(state.get("source_review_ids") or set()),
            "newest_review_date": parse_date(state.get("newest_review_date")),
        }
    return {
        "source_review_ids": set(),
        "newest_review_date": None,
    }


def review_seen_key(review: dict[str, Any]) -> str:
    review_key = first_nonempty(
        review.get("review_id"),
        (
            review.get("hotel_id"),
            review.get("reviewer_name"),
            review.get("review_date"),
            review.get("positive_text"),
            review.get("negative_text"),
            review.get("review_text"),
        ),
    )
    return json.dumps(review_key, ensure_ascii=False)


def should_collect_review(
    review: dict[str, Any],
    source_review_id: str,
    existing_source_review_ids: set[str],
    newest_review_date: date | None,
    cutoff_date: date | None,
) -> tuple[bool, bool, str | None]:
    parsed_review_date = parse_date(review.get("review_date"))
    if parsed_review_date and cutoff_date and parsed_review_date > cutoff_date:
        return False, False, "after_cutoff"
    if source_review_id in existing_source_review_ids:
        return False, True, "existing_id"
    if parsed_review_date and newest_review_date and parsed_review_date < newest_review_date:
        return False, True, "older_than_newest"
    return True, False, None


def is_review_graphql_request(request: Request) -> bool:
    if "/dml/graphql" not in request.url or request.method != "POST":
        return False
    body = parse_request_body(request)
    if not body:
        return False
    operation_name = str(body.get("operationName") or "").lower()
    query = str(body.get("query") or "").lower()
    combined = f"{operation_name}\n{query}"
    return (
        "review" in combined
        and "searchqueries" not in combined
        and "fullsearch" not in combined
    )


def update_review_pagination(value: Any, offset: int) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lower_key = key.lower()
            if lower_key in {"offset", "skip"}:
                value[key] = offset
            elif lower_key in {"rowsperpage", "limit", "first"}:
                value[key] = REVIEWS_PER_PAGE
            elif lower_key in {"page", "pagenumber"}:
                value[key] = (offset // REVIEWS_PER_PAGE) + 1
            else:
                update_review_pagination(child, offset)
    elif isinstance(value, list):
        for child in value:
            update_review_pagination(child, offset)


def looks_like_review(item: dict[str, Any]) -> bool:
    keys = " ".join(item.keys()).lower()
    return any(
        signal in keys
        for signal in [
            "reviewid",
            "review_id",
            "reviewer",
            "guestdetails",
            "positivetext",
            "negativetext",
            "pros",
            "cons",
            "reviewscore",
            "reviewdate",
            "publisheddate",
            "createddate",
            "bubblerating",
            "tripdate",
            "traveldate",
            "stayed",
        ]
    )


def find_review_items(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, list):
        dict_items = [item for item in value if isinstance(item, dict)]
        if dict_items and any(looks_like_review(item) for item in dict_items):
            return dict_items
        for item in value:
            found.extend(find_review_items(item))
    elif isinstance(value, dict):
        for child in value.values():
            found.extend(find_review_items(child))
    return found


def first_nested_text(
    data: dict[str, Any],
    paths: list[tuple[str, ...]],
) -> Any:
    for path in paths:
        value = translation_text(nested_get(data, *path))
        if value:
            return value
    return None


def first_nested_value(
    data: dict[str, Any],
    paths: list[tuple[str, ...]],
) -> Any:
    for path in paths:
        value = nested_get(data, *path)
        if value not in (None, "", [], {}):
            return value
    return None


def normalize_review(
    raw_review: dict[str, Any],
    hotel: dict[str, Any],
) -> dict[str, Any]:
    response = first_nonempty(
        first_nested_value(
            raw_review,
            [
                ("hotelResponse",),
                ("response",),
                ("managementResponse",),
                ("ownerResponse",),
            ],
        ),
        {},
    )
    if not isinstance(response, dict):
        response = {"text": response}

    return {
        "review_id": first_nested_value(
            raw_review,
            [("reviewId",), ("review_id",), ("id",), ("reviewUrlHash",)],
        ),
        "hotel_id": hotel.get("hotel_id"),
        "reviewer_name": first_nested_text(
            raw_review,
            [
                ("guestDetails", "username"),
                ("guestDetails", "userName"),
                ("reviewer", "name"),
                ("user", "name"),
                ("author", "name"),
            ],
        ),
        "reviewer_country": first_nested_text(
            raw_review,
            [
                ("guestDetails", "countryName"),
                ("guestDetails", "countryCode"),
                ("reviewer", "country"),
                ("user", "country"),
            ],
        ),
        "review_score": first_nested_value(
            raw_review,
            [("score",), ("reviewScore",), ("averageScore",), ("rating",)],
        ),
        "review_title": first_nested_text(
            raw_review,
            [("title",), ("reviewTitle",), ("headline",)],
        ),
        "positive_text": first_nested_text(
            raw_review,
            [
                ("positiveText",),
                ("pros",),
                ("likedText",),
                ("textDetails", "positiveText"),
            ],
        ),
        "negative_text": first_nested_text(
            raw_review,
            [
                ("negativeText",),
                ("cons",),
                ("dislikedText",),
                ("textDetails", "negativeText"),
            ],
        ),
        "review_text": first_nested_text(
            raw_review,
            [("text",), ("reviewText",), ("body",), ("comments",)],
        ),
        "review_date": first_nested_value(
            raw_review,
            [("date",), ("reviewDate",), ("createdDate",), ("submittedDate",)],
        ),
        "stayed_date": first_nested_value(
            raw_review,
            [("stayedDate",), ("stayDate",), ("travelDate",)],
        ),
        "room_name": first_nested_text(
            raw_review,
            [("roomDetails", "name"), ("roomName",)],
        ),
        "language": first_nested_value(
            raw_review,
            [("languageCode",), ("language",)],
        ),
        "response_id": first_nested_value(
            response,
            [("responseId",), ("id",), ("sourceResponseId",)],
        ),
        "response_text": first_nested_text(
            response,
            [("text",), ("responseText",), ("body",), ("message",)],
        ),
        "response_date": first_nested_value(
            response,
            [("date",), ("responseDate",), ("createdDate",), ("submittedDate",)],
        ),
        "responder_name": first_nested_text(
            response,
            [("responderName",), ("managerName",), ("author", "name")],
        ),
        "responder_role": first_nested_text(
            response,
            [("responderRole",), ("role",), ("author", "role")],
        ),
    }


async def wait_for_review_request(
    page: Page,
    hotel: dict[str, Any],
) -> Request | None:
    captured_request = None
    request_found = False

    async def request_handler(request: Request) -> None:
        nonlocal captured_request, request_found
        if captured_request is None and is_review_graphql_request(request):
            captured_request = request
            request_found = True

    page.on("request", request_handler)
    try:
        url = hotel_stay_url(hotel)
        if not url:
            return None
        await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        await accept_cookies(page)
        await page.wait_for_timeout(3000)

        for selector in [
            '[data-testid="review-score-link"]',
            'button:has-text("Guest reviews")',
            'a:has-text("Guest reviews")',
            'button:has-text("Read all reviews")',
            'button:has-text("See reviews")',
            'button:has-text("reviews")',
            'a:has-text("reviews")',
        ]:
            try:
                target = page.locator(selector).first
                if await target.is_visible(timeout=1000):
                    await target.click()
                    await page.wait_for_timeout(3000)
                    if request_found:
                        break
            except Exception:
                continue

        for _ in range(4):
            if request_found:
                break
            await page.evaluate(
                'window.scrollTo({top: document.body.scrollHeight, behavior: "smooth"})'
            )
            await page.wait_for_timeout(2500)
        return captured_request
    finally:
        try:
            page.remove_listener("request", request_handler)
        except Exception:
            pass


async def scrape_reviews_for_hotel(
    page: Page,
    hotel: dict[str, Any],
    increment_state: Any = None,
) -> list[dict[str, Any]]:
    normalized_state = normalize_increment_state(increment_state)
    existing_source_review_ids = normalized_state["source_review_ids"]
    newest_review_date = normalized_state["newest_review_date"]
    cutoff_date = review_cutoff_date()
    try:
        review_request = await wait_for_review_request(page, hotel)
    except Exception as error:
        print(f"  Review page could not be opened. Skipping hotel: {error}")
        return []
    if review_request is None:
        print("  No review API request captured. Trying reviewlist fallback.")
        return await scrape_reviewlist_fallback(
            page,
            hotel,
            normalized_state,
        )

    original_body = parse_request_body(review_request)
    if not isinstance(original_body, dict):
        print("  Could not parse review request body.")
        return []

    endpoint_url = review_request.url
    headers = await build_fetch_headers(review_request)
    reviews: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    empty_pages = 0
    no_new_pages = 0

    for page_number in range(MAX_REVIEW_PAGES_PER_HOTEL):
        offset = page_number * REVIEWS_PER_PAGE
        page_body = json.loads(json.dumps(original_body))
        update_review_pagination(page_body, offset)
        try:
            payload = await fetch_graphql_page(
                page=page,
                endpoint_url=endpoint_url,
                headers=headers,
                body=page_body,
            )
        except Exception as error:
            print(f"  Review page {page_number + 1} failed:", error)
            break

        raw_reviews = find_review_items(payload)
        if not raw_reviews:
            empty_pages += 1
            print(f"  Reviews page {page_number + 1}: 0 reviews")
            if empty_pages >= 2:
                break
            await page.wait_for_timeout(800)
            continue

        empty_pages = 0
        added = 0
        skipped = 0
        existing_encountered = False
        for raw_review in raw_reviews:
            review = normalize_review(raw_review, hotel)
            key = review_seen_key(review)
            source_review_id = stable_review_id(review)
            collect, should_stop, _reason = should_collect_review(
                review,
                source_review_id,
                existing_source_review_ids,
                newest_review_date,
                cutoff_date,
            )
            if not collect:
                skipped += 1
                if should_stop:
                    existing_encountered = True
                continue
            if key not in seen_keys:
                seen_keys.add(key)
                reviews.append(review)
                added += 1

        print(
            f"  Reviews page {page_number + 1}: received {len(raw_reviews)}, "
            f"new {added}, skipped {skipped}, total {len(reviews)}"
        )
        if existing_encountered:
            print("  Existing review reached. Stopping newer-only review collection.")
            break
        no_new_pages = no_new_pages + 1 if added == 0 else 0
        if no_new_pages >= 2 or len(raw_reviews) < REVIEWS_PER_PAGE:
            break
        await page.wait_for_timeout(800)
    return reviews


def extract_reviews_from_html(
    html_text: str,
    hotel: dict[str, Any],
) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    blocks = re.split(
        r'<li[^>]+class="[^"]*review_list_new_item_block[^"]*"',
        html_text,
        flags=re.IGNORECASE,
    )
    if len(blocks) == 1:
        blocks = re.split(
            r'<div[^>]+data-testid="review-card"[^>]*>',
            html_text,
            flags=re.IGNORECASE,
        )

    for block in blocks[1:]:
        def text_by_class(class_name: str) -> str | None:
            match = re.search(
                rf'class="[^"]*{re.escape(class_name)}[^"]*"[^>]*>(.*?)</',
                block,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not match:
                return None
            text = re.sub("<[^>]+>", " ", match.group(1))
            text = html.unescape(text)
            return re.sub(r"\s+", " ", text).strip() or None

        review = {
            "review_id": None,
            "hotel_id": hotel.get("hotel_id"),
            "reviewer_name": text_by_class("bui-avatar-block__title"),
            "reviewer_country": text_by_class("bui-avatar-block__subtitle"),
            "review_score": text_by_class("bui-review-score__badge"),
            "review_title": text_by_class("c-review-block__title"),
            "positive_text": text_by_class("c-review__row--positive"),
            "negative_text": text_by_class("c-review__row--negative"),
            "review_text": text_by_class("c-review__body"),
            "review_date": text_by_class("c-review-block__date"),
            "stayed_date": text_by_class("c-review-block__room-info"),
            "room_name": None,
            "language": None,
            "response_id": None,
            "response_text": None,
            "response_date": None,
            "responder_name": None,
            "responder_role": None,
        }
        if any(
            review.get(key)
            for key in [
                "reviewer_name",
                "review_score",
                "positive_text",
                "negative_text",
                "review_text",
            ]
        ):
            reviews.append(review)
    return reviews


async def fetch_reviewlist_page(
    page: Page,
    hotel: dict[str, Any],
    offset: int,
) -> dict[str, Any]:
    page_name = hotel.get("page_name")
    country_code = hotel.get("country_code")
    if not page_name or not country_code:
        return {"ok": False, "status": 0, "statusText": "Missing hotel path"}

    review_url = (
        "https://www.booking.com/reviewlist.en-gb.html"
        f"?cc1={quote_plus(str(country_code).lower())}"
        f"&pagename={quote_plus(str(page_name).strip('/').split('/')[-1])}"
        "&type=total"
        "&sort=f_recent_desc"
        f"&rows={REVIEWS_PER_PAGE}"
        f"&offset={offset}"
    )
    return await page.evaluate(
        """
        async (url) => {
            const response = await fetch(url, {credentials: "include"});
            const text = await response.text();
            let parsed = null;
            try { parsed = JSON.parse(text); } catch (error) { parsed = null; }
            return {ok: response.ok, status: response.status, statusText: response.statusText, text, json: parsed};
        }
        """,
        review_url,
    )


async def scrape_reviewlist_fallback(
    page: Page,
    hotel: dict[str, Any],
    increment_state: Any = None,
) -> list[dict[str, Any]]:
    normalized_state = normalize_increment_state(increment_state)
    existing_source_review_ids = normalized_state["source_review_ids"]
    newest_review_date = normalized_state["newest_review_date"]
    cutoff_date = review_cutoff_date()
    reviews: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    empty_pages = 0

    for page_number in range(MAX_REVIEW_PAGES_PER_HOTEL):
        offset = page_number * REVIEWS_PER_PAGE
        result = await fetch_reviewlist_page(page, hotel, offset)
        if not result.get("ok"):
            print(
                f"  Reviewlist offset {offset} failed: "
                f"{result.get('status')} {result.get('statusText')}"
            )
            break

        payload = result.get("json")
        if isinstance(payload, dict):
            page_reviews = [
                normalize_review(raw_review, hotel)
                for raw_review in find_review_items(payload)
            ]
        else:
            page_reviews = extract_reviews_from_html(
                str(result.get("text") or ""),
                hotel,
            )

        added = 0
        skipped = 0
        existing_encountered = False
        for review in page_reviews:
            key = review_seen_key(review)
            source_review_id = stable_review_id(review)
            collect, should_stop, _reason = should_collect_review(
                review,
                source_review_id,
                existing_source_review_ids,
                newest_review_date,
                cutoff_date,
            )
            if not collect:
                skipped += 1
                if should_stop:
                    existing_encountered = True
                continue
            if key not in seen_keys:
                seen_keys.add(key)
                reviews.append(review)
                added += 1

        print(
            f"  Reviewlist page {page_number + 1}: received {len(page_reviews)}, "
            f"new {added}, skipped {skipped}, total {len(reviews)}"
        )
        if existing_encountered:
            print("  Existing review reached. Stopping newer-only review collection.")
            break
        if not page_reviews:
            empty_pages += 1
            if empty_pages >= 2:
                break
        else:
            empty_pages = 0
        if len(page_reviews) < REVIEWS_PER_PAGE:
            break
        await page.wait_for_timeout(800)
    return reviews


async def scrape_reviews_for_hotels(
    context: BrowserContext,
    hotels: list[dict[str, Any]],
    incremental_state_by_hotel: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    incremental_state_by_hotel = incremental_state_by_hotel or {}
    available_hotels = [
        hotel
        for hotel in hotels
        if hotel.get("sold_out") is not True and hotel.get("property_url")
    ]
    all_reviews: list[dict[str, Any]] = []
    review_page = await context.new_page()
    try:
        print()
        print("=" * 60)
        print("COLLECTING HOTEL REVIEWS")
        print("=" * 60)
        print(f"Available hotels with URLs: {len(available_hotels)}")
        for index, hotel in enumerate(available_hotels, start=1):
            print(f"[{index}/{len(available_hotels)}] {hotel.get('name') or hotel.get('hotel_id')}")
            hotel_id = str(hotel.get("hotel_id") or "")
            try:
                reviews = await scrape_reviews_for_hotel(
                    review_page,
                    hotel,
                    incremental_state_by_hotel.get(hotel_id, {}),
                )
            except Exception as error:
                print(f"  Review collection failed. Skipping hotel: {error}")
                reviews = []
            all_reviews.extend(reviews)
            await review_page.wait_for_timeout(1200)
    finally:
        await review_page.close()
    return all_reviews
