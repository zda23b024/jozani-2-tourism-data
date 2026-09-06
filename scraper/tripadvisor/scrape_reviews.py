import hashlib
import html
import asyncio
import itertools
import json
import re
from typing import Any
from urllib.parse import urljoin

from playwright.async_api import BrowserContext, Page

from config.configuration import (
    MAX_TRIPADVISOR_REVIEW_PAGES,
    TRIPADVISOR_HOTEL_REVIEW_LANGUAGE_FILTER,
    TRIPADVISOR_REVIEW_GRAPHQL_ENABLED,
    TRIPADVISOR_REVIEW_GRAPHQL_QUERY_ID,
    TRIPADVISOR_REVIEW_GRAPHQL_URL,
    TRIPADVISOR_REVIEW_LANGUAGE,
    TRIPADVISOR_REVIEW_PLACE_LIMIT,
    TRIPADVISOR_REVIEW_PHOTOS_PER_REVIEW,
    TRIPADVISOR_RESTAURANT_REVIEWS_PER_PAGE,
    TRIPADVISOR_REVIEW_CONCURRENCY,
    TRIPADVISOR_REVIEWS_PER_PAGE,
)
from utils.browser_helpers import accept_cookies
from utils.console_output import print_review_header, print_review_progress
from utils.helpers import first_nonempty


TRIPADVISOR_SOURCE_ID = "tripadvisor"
TRIPADVISOR_REVIEW_GRAPHQL_MAX_RETRIES = 3


def review_page_numbers() -> range | itertools.count:
    if MAX_TRIPADVISOR_REVIEW_PAGES is None:
        return itertools.count()
    return range(MAX_TRIPADVISOR_REVIEW_PAGES)


def tripadvisor_review_url(place_url: str, page_number: int) -> str:
    if page_number <= 0:
        return place_url
    offset = page_number * TRIPADVISOR_REVIEWS_PER_PAGE
    if re.search(r"-Reviews-or\d+-", place_url):
        return re.sub(r"-Reviews-or\d+-", f"-Reviews-or{offset}-", place_url, count=1)
    return place_url.replace("-Reviews-", f"-Reviews-or{offset}-", 1)


def clean_text(value: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or None


def stable_visible_review_id(hotel_id: Any, review: dict[str, Any]) -> str:
    source = "|".join(
        str(review.get(key) or "")
        for key in [
            "review_id",
            "reviewer_name",
            "review_title",
            "review_text",
            "review_date",
        ]
    )
    return hashlib.sha256(f"{hotel_id}|{source}".encode("utf-8")).hexdigest()


def normalize_tripadvisor_review(raw_review: dict[str, Any], place: dict[str, Any]) -> dict[str, Any] | None:
    review_text = clean_text(raw_review.get("review_text"))
    review_title = clean_text(raw_review.get("review_title"))
    reviewer_name = clean_text(raw_review.get("reviewer_name"))
    if not any([review_text, review_title, reviewer_name]):
        return None

    hotel_id = str(
        first_nonempty(
            place.get("tripadvisor_id"),
            place.get("hotel_id"),
            place.get("attraction_id"),
            place.get("restaurant_id"),
            place.get("name"),
        )
    )
    place_id = place.get("place_id")
    place_source_id = place.get("place_source_id")
    review = {
        "source": TRIPADVISOR_SOURCE_ID,
        "hotel_id": hotel_id,
        "source_place_id": hotel_id,
        "place_id": place_id,
        "place_source_id": place_source_id,
        "review_id": clean_text(raw_review.get("review_id")),
        "reviewer_name": reviewer_name,
        "reviewer_country": clean_text(raw_review.get("reviewer_country")),
        "review_score": raw_review.get("review_score"),
        "review_title": review_title,
        "positive_text": review_text,
        "negative_text": None,
        "review_text": review_text,
        "review_date": clean_text(raw_review.get("review_date")),
        "stayed_date": clean_text(raw_review.get("stayed_date")),
        "room_name": None,
        "language": None,
        "response_id": None,
        "response_text": None,
        "response_date": None,
        "responder_name": None,
        "responder_role": None,
        "raw_json": raw_review,
    }
    review["review_id"] = review["review_id"] or stable_visible_review_id(hotel_id, review)
    return review


async def extract_visible_reviews(page: Page) -> list[dict[str, Any]]:
    return await page.evaluate(
        """
        () => {
            const text = (node) => (node?.innerText || node?.textContent || '').trim();
            const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
            const parseRating = (value) => {
                const match = String(value || '').match(/(\\d+(?:\\.\\d+)?)\\s+of\\s+5|rating[\\s:]+(\\d+(?:\\.\\d+)?)/i);
                return match ? Number(match[1] || match[2]) : null;
            };
            const reviewRoots = [
                ...document.querySelectorAll('[data-reviewid], [data-test-target*="review"], div[class*="review"], article')
            ];
            const candidates = reviewRoots
                .map((node) => {
                    const value = text(node);
                    return {node, value};
                })
                .filter((item) => {
                    const value = item.value;
                    if (value.length < 80 || value.length > 5000) return false;
                    if (/traveler rating|popular mentions|reviews? by traveler type|write a review|hotel deals/i.test(value)) return false;
                    return /review|read more|wrote a review|rated|bubble|trip type|date of stay|posted/i.test(value)
                        || item.node.hasAttribute('data-reviewid');
                });
            const minimal = candidates.filter((item) => {
                return !candidates.some((other) => other !== item && item.node.contains(other.node));
            });
            const seen = new Set();
            const reviews = [];

            for (const item of minimal) {
                const node = item.node;
                const lines = item.value.split('\\n').map((line) => clean(line)).filter(Boolean);
                const reviewId = node.getAttribute('data-reviewid') ||
                    node.querySelector('[data-reviewid]')?.getAttribute('data-reviewid') ||
                    null;
                const ratingLabel = node.querySelector('[aria-label*="bubble"], [aria-label*="rating"]')?.getAttribute('aria-label') || '';
                const reviewScore = parseRating(ratingLabel);
                const title = clean(
                    text(node.querySelector('[data-test-target*="review-title"], a[href*="#REVIEWS"], span[class*="title"], div[class*="title"]'))
                ) || lines.find((line) =>
                    line.length >= 4 &&
                    line.length <= 140 &&
                    !/review|bubble|date of stay|trip type|read more|wrote a review/i.test(line)
                ) || null;
                const dateLine = lines.find((line) =>
                    /date of stay|wrote a review|posted|visited|reviewed/i.test(line)
                ) || null;
                const tripLine = lines.find((line) => /trip type/i.test(line)) || null;
                const reviewerName = lines.find((line) =>
                    line.length >= 2 &&
                    line.length <= 80 &&
                    !/review|bubble|date of stay|trip type|read more|contributions|helpful/i.test(line) &&
                    line !== title
                ) || null;
                const bodyLines = lines
                    .filter((line) => line !== title)
                    .filter((line) => line !== reviewerName)
                    .filter((line) => line !== dateLine)
                    .filter((line) => line !== tripLine)
                    .filter((line) => !/^(read more|show less|helpful|share)$/i.test(line))
                    .filter((line) => line.length >= 25);
                const reviewText = bodyLines.join(' ');
                const key = reviewId || `${reviewerName}|${title}|${reviewText.slice(0, 120)}`;
                if (seen.has(key)) continue;
                seen.add(key);
                if (!reviewText && !title) continue;
                reviews.push({
                    review_id: reviewId,
                    reviewer_name: reviewerName,
                    reviewer_country: null,
                    review_score: reviewScore,
                    review_title: title,
                    review_text: reviewText,
                    review_date: dateLine,
                    stayed_date: tripLine,
                    raw_text: item.value
                });
            }
            return reviews.slice(0, 30);
        }
        """
    )


def text_from_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return clean_text(html.unescape(without_tags)) or ""


def extract_static_reviews_from_html(html_text: str) -> list[dict[str, Any]]:
    if not html_text:
        return []
    chunks = re.split(r'(?=<[^>]+(?:data-reviewid|id=["\']review_))', html_text)
    reviews = []
    seen: set[str] = set()
    for chunk in chunks:
        if len(chunk) < 300:
            continue
        if not re.search(r"review|bubble|date of stay|wrote a review", chunk, flags=re.IGNORECASE):
            continue
        text = text_from_html(chunk[:6000])
        if len(text) < 80:
            continue
        review_id_match = re.search(r'data-reviewid=["\']([^"\']+)["\']', chunk, flags=re.IGNORECASE)
        rating_match = re.search(r"(\d+(?:\.\d+)?)\s+of\s+5\s+bubbles", text, flags=re.IGNORECASE)
        date_match = re.search(
            r"((?:Date of stay|Reviewed|Wrote a review|Posted)[:\s]+[^.|\n]{3,80})",
            text,
            flags=re.IGNORECASE,
        )
        quoted = re.findall(r'"([^"]{25,1000})"', text)
        review_text = max(quoted, key=len) if quoted else text[:1200]
        title = None
        for line in re.split(r"\s{2,}| \| ", text):
            cleaned = clean_text(line)
            if cleaned and 4 <= len(cleaned) <= 140 and "review" not in cleaned.lower():
                title = cleaned
                break
        review_id = review_id_match.group(1) if review_id_match else hashlib.sha256(review_text.encode("utf-8")).hexdigest()
        if review_id in seen:
            continue
        seen.add(review_id)
        reviews.append(
            {
                "review_id": review_id,
                "reviewer_name": None,
                "reviewer_country": None,
                "review_score": float(rating_match.group(1)) if rating_match else None,
                "review_title": title,
                "review_text": clean_text(review_text),
                "review_date": clean_text(date_match.group(1)) if date_match else None,
                "stayed_date": None,
                "raw_text": text,
            }
        )
    return reviews


async def scrape_reviews_for_tripadvisor_hotel(
    page: Page,
    hotel: dict[str, Any],
) -> list[dict[str, Any]]:
    place_url = str(hotel.get("property_url") or "")
    if not place_url:
        return []

    reviews: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    stale_pages = 0

    for page_number in review_page_numbers():
        review_url = tripadvisor_review_url(place_url, page_number)
        try:
            await page.goto(review_url, wait_until="domcontentloaded", timeout=120_000)
            await accept_cookies(page)
            await page.wait_for_timeout(2500)
            raw_reviews = await extract_visible_reviews(page)
            if not raw_reviews:
                print(
                    "[TRIPADVISOR] No visible reviews detected; "
                    "static review HTML fallback is disabled."
                )
        except Exception as error:
            print(f"[TRIPADVISOR] Review page {page_number + 1} failed for {hotel.get('name')}: {error}")
            break

        added = 0
        for raw_review in raw_reviews:
            review = normalize_tripadvisor_review(raw_review, hotel)
            if not review:
                continue
            review_id = str(review.get("review_id") or "")
            if review_id in seen_ids:
                continue
            seen_ids.add(review_id)
            reviews.append(review)
            added += 1

        print(
            f"[TRIPADVISOR] Reviews page {page_number + 1} for "
            f"{hotel.get('name')}: received {len(raw_reviews)}, new {added}, total {len(reviews)}"
        )

        if not raw_reviews or added == 0:
            stale_pages += 1
        else:
            stale_pages = 0
        if stale_pages >= 2:
            break
        if len(raw_reviews) < TRIPADVISOR_REVIEWS_PER_PAGE:
            break
        await page.wait_for_timeout(1000)

    return reviews


def tripadvisor_review_graphql_configured() -> bool:
    return (
        TRIPADVISOR_REVIEW_GRAPHQL_ENABLED
        and bool(str(TRIPADVISOR_REVIEW_GRAPHQL_QUERY_ID or "").strip())
        and bool(str(TRIPADVISOR_REVIEW_GRAPHQL_URL or "").strip())
    )


def tripadvisor_place_location_id(place: dict[str, Any]) -> str | None:
    return clean_text(
        first_nonempty(
            place.get("tripadvisor_id"),
            place.get("location_id"),
            place.get("hotel_id"),
            place.get("attraction_id"),
            place.get("restaurant_id"),
        )
    )


def tripadvisor_place_source_url(place: dict[str, Any]) -> str | None:
    return clean_text(first_nonempty(place.get("property_url"), place.get("source_url")))


def tripadvisor_place_kind(place: dict[str, Any]) -> str:
    place_type_id = str(place.get("place_type_id") or "").lower()
    if place_type_id == "restaurant" or place.get("restaurant_id"):
        return "restaurant"
    if place.get("hotel_id") and place_type_id not in {
        "historical_site",
        "boat_tour",
        "restaurant",
    }:
        return "hotel"
    return "attraction"


def print_tripadvisor_review_diagnostics(places: list[dict[str, Any]]) -> None:
    hotels = [place for place in places if tripadvisor_place_kind(place) == "hotel"]
    restaurants = [
        place for place in places if tripadvisor_place_kind(place) == "restaurant"
    ]
    attractions = [
        place for place in places if tripadvisor_place_kind(place) == "attraction"
    ]

    print(f"Tripadvisor places total: {len(places)}")
    print(
        "with locationId: "
        f"{sum(1 for place in places if tripadvisor_place_location_id(place))}"
    )
    print(
        "with source URL: "
        f"{sum(1 for place in places if tripadvisor_place_source_url(place))}"
    )
    print(
        "hotels with URL: "
        f"{sum(1 for place in hotels if tripadvisor_place_source_url(place))}"
    )
    print(
        "attractions with URL: "
        f"{sum(1 for place in attractions if tripadvisor_place_source_url(place))}"
    )
    print(
        "restaurants with URL: "
        f"{sum(1 for place in restaurants if tripadvisor_place_source_url(place))}"
    )


def tripadvisor_language_filter(language: str | None) -> list[dict[str, Any]]:
    normalized = str(language or "").strip()
    if not normalized or normalized.lower() in {"all", "none", "null", "unlimited"}:
        return []
    return [
        {
            "axis": "LANGUAGE",
            "selections": [normalized],
        }
    ]


def review_graphql_payload(
    location_id: str,
    offset: int,
    place_kind: str = "hotel",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, limit or TRIPADVISOR_REVIEWS_PER_PAGE)
    if place_kind == "restaurant":
        review_variables = {
            "locationId": int(location_id),
            "limit": limit,
            "offset": offset,
            "filters": [
                {
                    "axis": "LANGUAGE",
                    "selections": [TRIPADVISOR_REVIEW_LANGUAGE],
                }
            ],
            "clientPage": "RESTAURANT_REVIEW",
            "sortType": None,
            "sortBy": "SERVER_DETERMINED",
            "language": TRIPADVISOR_REVIEW_LANGUAGE,
            "doMachineTranslation": True,
        }
    elif place_kind == "attraction":
        review_variables = {
            "locationId": int(location_id),
            "limit": limit,
            "offset": offset,
            "filters": [
                {
                    "axis": "LANGUAGE",
                    "selections": [TRIPADVISOR_REVIEW_LANGUAGE],
                }
            ],
            "sortType": "ML_SORTED",
            "sortBy": "FAVORABLE_RATING",
            "language": TRIPADVISOR_REVIEW_LANGUAGE,
            "doMachineTranslation": True,
            "photosPerReviewLimit": 7,
        }
    else:
        review_variables = {
            "locationId": int(location_id),
            "limit": limit,
            "offset": offset,
            "filters": tripadvisor_language_filter(TRIPADVISOR_HOTEL_REVIEW_LANGUAGE_FILTER),
            "clientPage": "HOTEL_REVIEW",
            "sortType": None,
            "sortBy": "SERVER_DETERMINED",
            "language": TRIPADVISOR_REVIEW_LANGUAGE,
            "doMachineTranslation": True,
            "photosPerReviewLimit": TRIPADVISOR_REVIEW_PHOTOS_PER_REVIEW,
        }
    return [
        {
            "variables": review_variables,
            "extensions": {
                "preRegisteredQueryId": TRIPADVISOR_REVIEW_GRAPHQL_QUERY_ID,
            },
        }
    ]


def first_nested_value(value: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if value.get(key) not in (None, "", [], {}):
                return value.get(key)
        for child in value.values():
            nested = first_nested_value(child, keys)
            if nested not in (None, "", [], {}):
                return nested
    if isinstance(value, list):
        for child in value:
            nested = first_nested_value(child, keys)
            if nested not in (None, "", [], {}):
                return nested
    return None


def text_value(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, str):
        return clean_text(html.unescape(re.sub(r"<[^>]+>", " ", value)))
    if isinstance(value, (int, float)):
        return clean_text(value)
    if isinstance(value, dict):
        direct = first_nested_value(
            value,
            (
                "text",
                "htmlText",
                "htmlString",
                "string",
                "value",
                "localizedString",
                "translation",
            ),
        )
        return text_value(direct) if direct is not value else None
    if isinstance(value, list):
        parts = [text_value(item) for item in value]
        return clean_text(" ".join(part for part in parts if part))
    return clean_text(value)


def numeric_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = clean_text(value)
    if not text:
        return None
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def normalize_tripadvisor_review_date(value: Any) -> str | None:
    if isinstance(value, dict):
        return clean_text(
            first_nonempty(
                value.get("isoDate"),
                value.get("date"),
                value.get("string"),
                value.get("text"),
                value.get("localizedString"),
            )
        )
    return clean_text(value)


def tripadvisor_review_url_from_raw(raw_review: dict[str, Any]) -> str | None:
    raw_url = first_nonempty(
        raw_review.get("url"),
        raw_review.get("reviewUrl"),
        raw_review.get("detailUrl"),
        raw_review.get("webUrl"),
        first_nested_value(raw_review, ("reviewUrl", "detailUrl")),
    )
    url = clean_text(raw_url)
    if not url:
        return None
    return urljoin("https://www.tripadvisor.com", url)


def normalize_management_response(raw_review: dict[str, Any]) -> dict[str, Any]:
    response = first_nonempty(
        raw_review.get("mgmtResponse"),
        raw_review.get("managementResponse"),
        raw_review.get("ownerResponse"),
        raw_review.get("response"),
    )
    if not isinstance(response, dict):
        return {}
    response_text = text_value(
        first_nonempty(
            response.get("text"),
            response.get("body"),
            response.get("response"),
            response.get("htmlText"),
        )
    )
    response_id = clean_text(
        first_nonempty(
            response.get("id"),
            response.get("responseId"),
            response.get("objectId"),
        )
    )
    responder = first_nonempty(
        response.get("responder"),
        response.get("userProfile"),
        response.get("user"),
        {},
    )
    return {
        "response_id": response_id,
        "response_text": response_text,
        "response_date": normalize_tripadvisor_review_date(
            first_nonempty(
                response.get("createdDate"),
                response.get("publishedDate"),
                response.get("date"),
            )
        ),
        "responder_name": text_value(
            first_nonempty(
                response.get("responderName"),
                responder.get("displayName") if isinstance(responder, dict) else None,
                responder.get("username") if isinstance(responder, dict) else None,
                responder.get("name") if isinstance(responder, dict) else None,
            )
        ),
        "responder_role": text_value(
            first_nonempty(
                response.get("responderRole"),
                response.get("role"),
                response.get("title"),
            )
        ),
        "response_raw_json": response,
    }


def tripadvisor_user_profile_url(user_profile: Any) -> str | None:
    if not isinstance(user_profile, dict):
        return None
    route = user_profile.get("route")
    raw_url = first_nonempty(
        route.get("url") if isinstance(route, dict) else None,
        user_profile.get("profileUrl"),
        user_profile.get("url"),
    )
    url = clean_text(raw_url)
    return urljoin("https://www.tripadvisor.com", url) if url else None


def tripadvisor_hometown_name(user_profile: Any) -> str | None:
    if not isinstance(user_profile, dict):
        return None
    hometown = user_profile.get("hometown")
    if not isinstance(hometown, dict):
        return text_value(first_nonempty(user_profile.get("location"), user_profile.get("country")))
    location = hometown.get("location")
    additional_names = location.get("additionalNames") if isinstance(location, dict) else None
    if isinstance(additional_names, dict):
        return text_value(
            first_nonempty(
                additional_names.get("long"),
                additional_names.get("name"),
            )
        )
    return text_value(first_nonempty(hometown, user_profile.get("location"), user_profile.get("country")))


def tripadvisor_reviewer_level(user_profile: Any) -> str | None:
    if not isinstance(user_profile, dict):
        return None
    counts = user_profile.get("contributionCounts")
    if not isinstance(counts, dict):
        return None
    helpful = counts.get("helpfulVote")
    total = counts.get("sumAllUgc")
    parts = []
    if total not in (None, ""):
        parts.append(f"contributions={total}")
    if helpful not in (None, ""):
        parts.append(f"helpful_votes={helpful}")
    return "; ".join(parts) or None


def normalize_additional_ratings(raw_review: dict[str, Any]) -> list[dict[str, Any]]:
    ratings = raw_review.get("additionalRatings") or []
    if not isinstance(ratings, list):
        return []
    normalized = []
    seen: set[str] = set()
    for item in ratings:
        if not isinstance(item, dict):
            continue
        label = text_value(
            first_nonempty(
                item.get("ratingLabelLocalizedString"),
                item.get("label"),
                item.get("name"),
            )
        )
        score = numeric_value(item.get("rating"))
        if not label or score is None:
            continue
        key = safe_label = clean_text(label) or label
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"category_name": safe_label, "score": score})
    return normalized


def normalize_graphql_review(raw_review: dict[str, Any], place: dict[str, Any]) -> dict[str, Any] | None:
    location_id = tripadvisor_place_location_id(place)
    if not location_id:
        return None

    user_profile = raw_review.get("userProfile") or raw_review.get("user") or {}
    trip_info = raw_review.get("tripInfo") or {}
    review_id = clean_text(first_nonempty(raw_review.get("id"), raw_review.get("reviewId")))
    review_text = text_value(
        first_nonempty(
            raw_review.get("text"),
            raw_review.get("body"),
            raw_review.get("reviewText"),
            raw_review.get("htmlText"),
        )
    )
    review_title = text_value(first_nonempty(raw_review.get("title"), raw_review.get("heading")))
    reviewer_name = text_value(
        first_nonempty(
            user_profile.get("displayName") if isinstance(user_profile, dict) else None,
            user_profile.get("username") if isinstance(user_profile, dict) else None,
            user_profile.get("name") if isinstance(user_profile, dict) else None,
            raw_review.get("username"),
        )
    )
    if not any([review_id, review_text, review_title, reviewer_name]):
        return None

    review = {
        "source": TRIPADVISOR_SOURCE_ID,
        "hotel_id": location_id,
        "source_place_id": location_id,
        "place_id": place.get("place_id"),
        "place_source_id": place.get("place_source_id"),
        "review_id": review_id,
        "reviewer_id": clean_text(
            first_nonempty(
                user_profile.get("id") if isinstance(user_profile, dict) else None,
                user_profile.get("userId") if isinstance(user_profile, dict) else None,
                user_profile.get("profileId") if isinstance(user_profile, dict) else None,
            )
        ),
        "reviewer_name": reviewer_name,
        "reviewer_country": tripadvisor_hometown_name(user_profile),
        "reviewer_level": tripadvisor_reviewer_level(user_profile),
        "reviewer_profile_url": tripadvisor_user_profile_url(user_profile),
        "review_score": numeric_value(raw_review.get("rating")),
        "review_title": review_title,
        "positive_text": review_text,
        "negative_text": None,
        "review_text": review_text,
        "review_date": normalize_tripadvisor_review_date(
            first_nonempty(
                raw_review.get("publishedDate"),
                raw_review.get("createdDate"),
                raw_review.get("date"),
            )
        ),
        "stayed_date": text_value(
            first_nonempty(
                trip_info.get("stayDate") if isinstance(trip_info, dict) else None,
                trip_info.get("tripDate") if isinstance(trip_info, dict) else None,
                trip_info.get("travelDate") if isinstance(trip_info, dict) else None,
                raw_review.get("tripDate"),
            )
        ),
        "room_name": text_value(
            first_nonempty(
                trip_info.get("roomName") if isinstance(trip_info, dict) else None,
                trip_info.get("roomType") if isinstance(trip_info, dict) else None,
            )
        ),
        "language": clean_text(
            first_nonempty(raw_review.get("language"), raw_review.get("originalLanguage"))
        ),
        "trip_type": text_value(trip_info.get("tripType") if isinstance(trip_info, dict) else None),
        "helpful_votes": numeric_value(raw_review.get("helpfulVotes")),
        "additional_ratings": normalize_additional_ratings(raw_review),
        "source_url": tripadvisor_review_url_from_raw(raw_review),
        "raw_json": raw_review,
    }
    review.update(normalize_management_response(raw_review))
    review["review_id"] = review["review_id"] or stable_visible_review_id(location_id, review)
    return review


def extract_review_page_payload(response_json: Any) -> tuple[int | None, list[dict[str, Any]]]:
    try:
        page_data = (
            response_json[0]
            .get("data", {})
            .get("ReviewsProxy_getReviewListPageForLocation", [])
        )
        page_payload = page_data[0]
    except (TypeError, KeyError, IndexError):
        return None, []
    if not isinstance(page_payload, dict):
        return None, []
    reviews = page_payload.get("reviews") or []
    if not isinstance(reviews, list):
        reviews = []
    total_count = page_payload.get("totalCount")
    try:
        total_count = int(total_count) if total_count not in (None, "") else None
    except (TypeError, ValueError):
        total_count = None
    return total_count, [review for review in reviews if isinstance(review, dict)]


def valid_review_total(value: Any) -> int | None:
    if not isinstance(value, int) or value < 0:
        return None
    return value


async def fetch_tripadvisor_reviews_page(
    page: Page,
    place: dict[str, Any],
    location_id: str,
    place_kind: str,
    offset: int,
    limit: int | None = None,
) -> dict[str, Any]:
    referer = tripadvisor_place_source_url(place) or "https://www.tripadvisor.com/"
    payload = review_graphql_payload(location_id, offset, place_kind, limit)
    headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://www.tripadvisor.com",
        "referer": referer,
    }
    delay_ms = 1000
    for attempt in range(1, TRIPADVISOR_REVIEW_GRAPHQL_MAX_RETRIES + 1):
        try:
            response = await page.context.request.post(
                TRIPADVISOR_REVIEW_GRAPHQL_URL,
                data=json.dumps(payload),
                headers=headers,
                timeout=60_000,
            )
        except Exception as error:
            print(
                f"[TRIPADVISOR][REVIEWS] GraphQL request failed for "
                f"{place.get('name')} offset={offset} attempt {attempt}: {error}"
            )
            if attempt >= TRIPADVISOR_REVIEW_GRAPHQL_MAX_RETRIES:
                return {"total_count": None, "reviews": []}
            await page.wait_for_timeout(delay_ms)
            delay_ms *= 2
            continue
        if response.ok:
            try:
                total_count, reviews = extract_review_page_payload(await response.json())
                return {"total_count": total_count, "reviews": reviews}
            except Exception as error:
                print(
                    f"[TRIPADVISOR][REVIEWS] Could not parse review GraphQL JSON "
                    f"for {place.get('name')}: {error}"
                )
                return {"total_count": None, "reviews": []}
        status = response.status
        print(
            f"[TRIPADVISOR][{review_log_label(place_kind)}] GraphQL status {status} for "
            f"{place.get('name')} offset={offset} attempt {attempt}"
        )
        if status == 403:
            print("[TRIPADVISOR][REVIEWS] Access refused/challenged; skipping place.")
            return {"total_count": None, "reviews": []}
        if status not in {429, 500, 502, 503, 504}:
            return {"total_count": None, "reviews": []}
        await page.wait_for_timeout(delay_ms)
        delay_ms *= 2
    return {"total_count": None, "reviews": []}


async def fetch_tripadvisor_hotel_reviews_page(
    page: Page,
    place: dict[str, Any],
    location_id: str,
    offset: int,
    limit: int | None = None,
) -> dict[str, Any]:
    return await fetch_tripadvisor_reviews_page(
        page,
        place,
        location_id,
        "hotel",
        offset,
        limit,
    )


async def fetch_tripadvisor_attraction_reviews_page(
    page: Page,
    place: dict[str, Any],
    location_id: str,
    offset: int,
    limit: int | None = None,
) -> dict[str, Any]:
    return await fetch_tripadvisor_reviews_page(
        page,
        place,
        location_id,
        "attraction",
        offset,
        limit,
    )


async def fetch_tripadvisor_restaurant_reviews_page(
    page: Page,
    place: dict[str, Any],
    location_id: str,
    offset: int,
    limit: int | None = None,
) -> dict[str, Any]:
    return await fetch_tripadvisor_reviews_page(
        page,
        place,
        location_id,
        "restaurant",
        offset,
        limit,
    )


async def fetch_review_graphql_page(
    page: Page,
    place: dict[str, Any],
    location_id: str,
    offset: int,
) -> tuple[int | None, list[dict[str, Any]]]:
    result = await fetch_tripadvisor_hotel_reviews_page(
        page,
        place,
        location_id,
        offset,
    )
    return result.get("total_count"), result.get("reviews", [])


def review_log_label(place_kind: str) -> str:
    if place_kind == "restaurant":
        return "RESTAURANT REVIEWS"
    if place_kind == "attraction":
        return "ATTRACTION REVIEWS"
    return "REVIEWS"


def review_place_label(place_kind: str) -> str:
    if place_kind == "restaurant":
        return "Restaurant"
    if place_kind == "attraction":
        return "Attraction"
    return "Hotel"


def review_limit_for_place_kind(place_kind: str) -> int:
    if place_kind == "restaurant":
        return max(1, TRIPADVISOR_RESTAURANT_REVIEWS_PER_PAGE)
    return max(1, TRIPADVISOR_REVIEWS_PER_PAGE)


async def scrape_reviews_for_tripadvisor_place_graphql(
    page: Page,
    place: dict[str, Any],
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> list[dict[str, Any]]:
    location_id = tripadvisor_place_location_id(place)
    if not location_id:
        print("[TRIPADVISOR][REVIEWS] Missing Tripadvisor locationId; skipping place.")
        return []

    try:
        int(location_id)
    except (TypeError, ValueError):
        print(
            f"[TRIPADVISOR][REVIEWS] Invalid Tripadvisor locationId "
            f"for {place.get('name')}: {location_id}"
        )
        return []

    place_kind = tripadvisor_place_kind(place)
    if place_kind not in {"hotel", "attraction", "restaurant"}:
        return []

    reviews: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    limit = review_limit_for_place_kind(place_kind)
    offset = 0
    pages_fetched = 0
    last_page_ids: tuple[str, ...] | None = None
    log_label = review_log_label(place_kind)
    place_label = review_place_label(place_kind)

    known_total_count: int | None = None
    stop_reason = "not_started"

    while True:
        result = await fetch_tripadvisor_reviews_page(
            page,
            place,
            location_id,
            place_kind,
            offset,
            limit,
        )
        pages_fetched += 1
        total_count = result.get("total_count")
        page_total_count = valid_review_total(total_count)
        if page_total_count is not None:
            known_total_count = page_total_count
        raw_reviews = result.get("reviews", [])
        if not isinstance(raw_reviews, list):
            raw_reviews = []

        page_ids = tuple(
            str(raw_review.get("id") or raw_review.get("reviewId") or "")
            for raw_review in raw_reviews
            if isinstance(raw_review, dict)
        )
        added = 0
        for raw_review in raw_reviews:
            review = normalize_graphql_review(raw_review, place)
            if not review:
                continue
            review_id = str(review.get("review_id") or "")
            if review_id in seen_ids:
                continue
            seen_ids.add(review_id)
            reviews.append(review)
            added += 1

        if not raw_reviews:
            stop_reason = "empty_reviews"
            break
        if added == 0:
            stop_reason = "no_new_review_ids"
            break
        if last_page_ids is not None and page_ids and page_ids == last_page_ids:
            stop_reason = "repeated_page_ids"
            print(f"[TRIPADVISOR][{log_label}] Repeated review page detected; stopping place.")
            break
        last_page_ids = page_ids

        offset += limit

        if known_total_count is not None and len(reviews) >= known_total_count:
            stop_reason = "known_total_reached"
            break
        if len(raw_reviews) < limit:
            stop_reason = "short_page"
            break
        if (
            MAX_TRIPADVISOR_REVIEW_PAGES is not None
            and pages_fetched >= MAX_TRIPADVISOR_REVIEW_PAGES
        ):
            stop_reason = "configured_page_limit"
            print(
                f"[TRIPADVISOR][{log_label}] Test page limit reached: "
                f"{MAX_TRIPADVISOR_REVIEW_PAGES}"
            )
            break
        await page.wait_for_timeout(1000)

    print(
        f"[TRIPADVISOR][{log_label}] {place_label}: {place.get('name') or location_id} | "
        f"pages requested: {pages_fetched} | stop reason: {stop_reason}"
    )
    if progress_index is not None and progress_total is not None:
        print_review_progress(
            progress_index,
            progress_total,
            place.get("name") or location_id,
            len(reviews),
            known_total_count,
        )
    return reviews


def limit_review_places(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if TRIPADVISOR_REVIEW_PLACE_LIMIT is None:
        return places
    return places[:TRIPADVISOR_REVIEW_PLACE_LIMIT]


async def scrape_reviews_for_tripadvisor_places(
    context: BrowserContext,
    places: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reviewable_places = [
        place
        for place in places
        if tripadvisor_place_location_id(place)
    ]
    all_reviewable_hotels = [
        place
        for place in reviewable_places
        if tripadvisor_place_kind(place) == "hotel" and tripadvisor_place_location_id(place)
    ]
    all_reviewable_attractions = [
        place
        for place in reviewable_places
        if tripadvisor_place_kind(place) == "attraction" and tripadvisor_place_location_id(place)
    ]
    all_reviewable_restaurants = [
        place
        for place in reviewable_places
        if tripadvisor_place_kind(place) == "restaurant" and tripadvisor_place_location_id(place)
    ]
    reviewable_hotels = limit_review_places(all_reviewable_hotels)
    reviewable_attractions = limit_review_places(all_reviewable_attractions)
    reviewable_restaurants = limit_review_places(all_reviewable_restaurants)
    selected_places = reviewable_hotels + reviewable_attractions + reviewable_restaurants
    print_tripadvisor_review_diagnostics(places)
    all_reviews: list[dict[str, Any]] = []
    concurrency = max(1, min(TRIPADVISOR_REVIEW_CONCURRENCY, len(selected_places) or 1))

    if reviewable_hotels:
        print_review_header("Hotel")
    if reviewable_attractions:
        print_review_header("Attraction")
    if reviewable_restaurants:
        print_review_header("Restaurant")
    print(f"[TRIPADVISOR] Hotel review places selected: {len(reviewable_hotels)}")
    print(f"[TRIPADVISOR] Attraction review places selected: {len(reviewable_attractions)}")
    print(f"[TRIPADVISOR] Restaurant review places selected: {len(reviewable_restaurants)}")
    if TRIPADVISOR_REVIEW_PLACE_LIMIT is not None:
        print(
            "[TRIPADVISOR] Review place test limit per supported place type: "
            f"{TRIPADVISOR_REVIEW_PLACE_LIMIT}"
        )
    print(f"[TRIPADVISOR] Review concurrency: {concurrency}")

    if not selected_places:
        return all_reviews
    if not tripadvisor_review_graphql_configured():
        print(
            "[TRIPADVISOR][REVIEWS] Structured review endpoint not configured; "
            "skipping review collection."
        )
        return all_reviews

    queue: asyncio.Queue[tuple[int, dict[str, Any]]] = asyncio.Queue()
    for item in enumerate(selected_places, start=1):
        queue.put_nowait(item)

    async def worker(worker_number: int) -> None:
        page = await context.new_page()
        try:
            while True:
                try:
                    index, hotel = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return

                try:
                    reviews = await scrape_reviews_for_tripadvisor_place_graphql(
                        page,
                        hotel,
                        index,
                        len(selected_places),
                    )
                except Exception as error:
                    print(f"[TRIPADVISOR] Failed to collect reviews for {hotel.get('name')}: {error}")
                    print_review_progress(
                        index,
                        len(selected_places),
                        hotel.get("name"),
                        0,
                        failed=True,
                    )
                    reviews = []
                finally:
                    queue.task_done()
                all_reviews.extend(reviews)
                await page.wait_for_timeout(1000)
        finally:
            await page.close()

    await asyncio.gather(*(worker(index) for index in range(1, concurrency + 1)))
    attraction_review_count = sum(
        1
        for review in all_reviews
        if any(
            review.get("place_source_id") == place.get("place_source_id")
            for place in reviewable_attractions
        )
    )
    restaurant_review_count = sum(
        1
        for review in all_reviews
        if any(
            review.get("place_source_id") == place.get("place_source_id")
            for place in reviewable_restaurants
        )
    )
    print(f"[TRIPADVISOR] Attraction reviews collected: {attraction_review_count}")
    print(f"[TRIPADVISOR] Restaurant reviews collected: {restaurant_review_count}")
    return all_reviews


async def scrape_reviews_for_tripadvisor_hotels(
    context: BrowserContext,
    hotels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return await scrape_reviews_for_tripadvisor_places(context, hotels)
