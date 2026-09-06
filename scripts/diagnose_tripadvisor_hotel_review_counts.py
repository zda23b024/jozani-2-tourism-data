import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from playwright.async_api import Error as PlaywrightError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.configuration import (  # noqa: E402
    OUTPUT_DIR,
    TRIPADVISOR_BROWSER_PROFILE_DIR,
    TRIPADVISOR_REVIEW_GRAPHQL_URL,
    TRIPADVISOR_REVIEWS_PER_PAGE,
)
from scraper.tripadvisor.scrape_reviews import (  # noqa: E402
    extract_review_page_payload,
    normalize_graphql_review,
    review_graphql_payload,
    valid_review_total,
)
from utils.browser_helpers import accept_cookies, close_context, launch_context  # noqa: E402


HOTELS = [
    {
        "name": "Essque Zalu Zanzibar",
        "tripadvisor_id": "2076584",
        "property_url": "https://www.tripadvisor.com/Hotel_Review-g616016-d2076584-Reviews-Essque_Zalu_Zanzibar-Nungwi_Zanzibar_Island_Zanzibar_Archipelago.html",
    },
    {
        "name": "Diamonds Bijoux",
        "tripadvisor_id": "33101312",
        "property_url": "https://www.tripadvisor.com/Hotel_Review-g482884-d33101312-Reviews-Diamonds_Bijoux-Zanzibar_Island_Zanzibar_Archipelago.html",
    },
    {
        "name": "Tembo House Hotel",
        "tripadvisor_id": "593744",
        "property_url": "https://www.tripadvisor.com/Hotel_Review-g488129-d593744-Reviews-Tembo_House_Hotel-Stone_Town_Zanzibar_City_Zanzibar_Island_Zanzibar_Archipelago.html",
    },
    {
        "name": "Royal Zanzibar Beach Resort",
        "tripadvisor_id": "1175635",
        "property_url": "https://www.tripadvisor.com/Hotel_Review-g616016-d1175635-Reviews-Royal_Zanzibar_Beach_Resort-Nungwi_Zanzibar_Island_Zanzibar_Archipelago.html",
    },
    {
        "name": "Meliá Zanzibar",
        "tripadvisor_id": "585857",
        "property_url": "https://www.tripadvisor.com/Hotel_Review-g616018-d585857-Reviews-Melia_Zanzibar-Kiwengwa_Zanzibar_Island_Zanzibar_Archipelago.html",
    },
]
DEBUG_DIR = OUTPUT_DIR / "debug" / "tripadvisor" / "hotel_review_count_diagnostics"
DIAGNOSTIC_PROFILE_DIR = DEBUG_DIR / "browser_profile"
SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "cookies",
    "csrf",
    "security",
    "session",
    "token",
    "x-tripadvisor-unique",
}


def filename_slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    return "_".join(part for part in slug.split("_") if part)


def sanitized(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            lowered = str(key).lower()
            if any(secret in lowered for secret in SENSITIVE_KEYS):
                result[key] = "[redacted]"
            else:
                result[key] = sanitized(child)
        return result
    if isinstance(value, list):
        return [sanitized(child) for child in value]
    return value


def response_path_present(response_json: Any) -> bool:
    try:
        page_payload = response_json[0]["data"]["ReviewsProxy_getReviewListPageForLocation"][0]
    except (TypeError, KeyError, IndexError):
        return False
    return isinstance(page_payload, dict)


def page_fingerprint(review_ids: tuple[str, ...]) -> str:
    return hashlib.sha256("|".join(review_ids).encode("utf-8")).hexdigest()


async def fetch_raw_page(page, hotel: dict[str, Any], offset: int) -> dict[str, Any]:
    payload = review_graphql_payload(
        str(hotel["tripadvisor_id"]),
        offset,
        "hotel",
        TRIPADVISOR_REVIEWS_PER_PAGE,
    )
    request_summary = {
        "url": TRIPADVISOR_REVIEW_GRAPHQL_URL,
        "payload": sanitized(payload),
        "offset": offset,
        "limit": TRIPADVISOR_REVIEWS_PER_PAGE,
    }
    try:
        response = await page.context.request.post(
            TRIPADVISOR_REVIEW_GRAPHQL_URL,
            data=json.dumps(payload),
            headers={
                "accept": "*/*",
                "content-type": "application/json",
                "origin": "https://www.tripadvisor.com",
                "referer": hotel["property_url"],
            },
            timeout=60_000,
        )
    except Exception as error:  # noqa: BLE001
        return {
            "request": request_summary,
            "response": {
                "http_status": 0,
                "content_type": "",
                "ok": False,
                "path": "[0].data.ReviewsProxy_getReviewListPageForLocation[0]",
                "path_present": False,
                "totalCount": None,
                "totalCount_missing": True,
                "reviews_returned": 0,
                "review_ids": [],
                "fingerprint": page_fingerprint(()),
                "parse_error": None,
                "request_error": str(error).splitlines()[0],
                "body_preview": None,
            },
            "parsed_response": None,
            "reviews": [],
        }
    text = await response.text()
    parsed: Any = None
    total_count = None
    reviews: list[dict[str, Any]] = []
    parse_error = None
    try:
        parsed = json.loads(text)
        total_count, reviews = extract_review_page_payload(parsed)
    except Exception as error:  # noqa: BLE001
        parse_error = str(error)

    review_ids = tuple(
        str(review.get("id") or review.get("reviewId") or "")
        for review in reviews
        if isinstance(review, dict)
    )
    return {
        "request": request_summary,
        "response": {
            "http_status": response.status,
            "content_type": response.headers.get("content-type", ""),
            "ok": response.ok,
            "path": "[0].data.ReviewsProxy_getReviewListPageForLocation[0]",
            "path_present": response_path_present(parsed),
            "totalCount": total_count,
            "totalCount_missing": total_count is None,
            "reviews_returned": len(reviews),
            "review_ids": review_ids,
            "fingerprint": page_fingerprint(review_ids),
            "parse_error": parse_error,
            "request_error": None,
            "body_preview": None if response.ok else text[:1500],
        },
        "parsed_response": sanitized(parsed),
        "reviews": reviews,
    }


async def diagnose_hotel(page, hotel: dict[str, Any]) -> dict[str, Any]:
    reviews = []
    seen_ids: set[str] = set()
    known_total = None
    offset = 0
    pages_requested = 0
    first_page = None
    final_page = None
    last_page_ids = None
    stop_reason = "not_started"

    try:
        await page.goto(hotel["property_url"], wait_until="domcontentloaded", timeout=120_000)
    except Exception as error:  # noqa: BLE001
        stop_reason = "hotel_page_warmup_failed"
        diagnostic = {
            "hotel": hotel["name"],
            "locationId": hotel["tripadvisor_id"],
            "api_total": None,
            "collected_unique": 0,
            "pages_requested": 0,
            "stop_reason": stop_reason,
            "status": "UNKNOWN",
            "warmup_error": str(error).splitlines()[0],
        }
        output_path = DEBUG_DIR / f"{filename_slug(hotel['name'])}.json"
        output_path.write_text(
            json.dumps(diagnostic, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Hotel: {hotel['name']}")
        print(f"locationId: {hotel['tripadvisor_id']}")
        print(f"stop reason: {stop_reason}")
        print()
        return diagnostic
    await accept_cookies(page)
    await page.wait_for_timeout(1500)

    while True:
        result = await fetch_raw_page(page, hotel, offset)
        pages_requested += 1
        if first_page is None:
            first_page = result
        final_page = result

        total_count = result["response"]["totalCount"]
        page_total = valid_review_total(total_count)
        if page_total is not None:
            known_total = page_total

        raw_reviews = result["reviews"]
        page_ids = tuple(
            str(raw_review.get("id") or raw_review.get("reviewId") or "")
            for raw_review in raw_reviews
            if isinstance(raw_review, dict)
        )

        added = 0
        for raw_review in raw_reviews:
            review = normalize_graphql_review(raw_review, hotel)
            if not review:
                continue
            review_id = str(review.get("review_id") or "")
            if review_id in seen_ids:
                continue
            seen_ids.add(review_id)
            reviews.append(review)
            added += 1

        print(f"Hotel: {hotel['name']}")
        print(f"locationId: {hotel['tripadvisor_id']}")
        print(f"HTTP status: {result['response']['http_status']}")
        print(f"offset: {offset}")
        print(f"reviews received: {len(raw_reviews)}")
        print(f"totalCount: {total_count if total_count is not None else 'missing'}")
        print(f"new unique reviews: {added}")

        if not raw_reviews:
            stop_reason = "request_failed" if result["response"].get("request_error") else "empty_reviews"
            break
        if added == 0:
            stop_reason = "no_new_review_ids"
            break
        if last_page_ids is not None and page_ids and page_ids == last_page_ids:
            stop_reason = "repeated_page_ids"
            break
        last_page_ids = page_ids
        offset += TRIPADVISOR_REVIEWS_PER_PAGE
        if known_total is not None and len(reviews) >= known_total:
            stop_reason = "known_total_reached"
            break
        if len(raw_reviews) < TRIPADVISOR_REVIEWS_PER_PAGE:
            stop_reason = "short_page"
            break

    status = "UNKNOWN" if known_total is None else ("OK" if len(reviews) == known_total else "WARN")
    diagnostic = {
        "hotel": hotel["name"],
        "locationId": hotel["tripadvisor_id"],
        "api_total": known_total,
        "collected_unique": len(reviews),
        "pages_requested": pages_requested,
        "stop_reason": stop_reason,
        "status": status,
        "first_review_request": first_page["request"] if first_page else None,
        "first_response": first_page["response"] if first_page else None,
        "first_response_json": first_page["parsed_response"] if first_page else None,
        "final_request_before_stopping": final_page["request"] if final_page else None,
        "final_response_before_stopping": final_page["response"] if final_page else None,
        "final_response_json_before_stopping": final_page["parsed_response"] if final_page else None,
    }
    output_path = DEBUG_DIR / f"{filename_slug(hotel['name'])}.json"
    output_path.write_text(
        json.dumps(diagnostic, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"stop reason: {stop_reason}")
    print()
    return diagnostic


async def main() -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        context = await launch_context(TRIPADVISOR_BROWSER_PROFILE_DIR, "Tripadvisor")
    except PlaywrightError as error:
        if "Opening in existing browser session" in str(error):
            print("Tripadvisor browser profile is already in use.")
            print(f"Retrying with diagnostic profile: {DIAGNOSTIC_PROFILE_DIR}")
            context = await launch_context(DIAGNOSTIC_PROFILE_DIR, "Tripadvisor diagnostic")
        else:
            raise

    page = context.pages[0] if context.pages else await context.new_page()
    try:
        results = []
        for hotel in HOTELS:
            try:
                results.append(await diagnose_hotel(page, hotel))
            except Exception as error:  # noqa: BLE001
                result = {
                    "hotel": hotel["name"],
                    "locationId": hotel["tripadvisor_id"],
                    "api_total": None,
                    "collected_unique": 0,
                    "pages_requested": 0,
                    "stop_reason": "diagnostic_error",
                    "status": "UNKNOWN",
                    "error": str(error).splitlines()[0],
                }
                results.append(result)
                output_path = DEBUG_DIR / f"{filename_slug(hotel['name'])}.json"
                output_path.write_text(
                    json.dumps(result, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

        print("Controlled Tripadvisor hotel review diagnostic")
        print()
        print("Hotel | API total | Collected unique | Pages requested | Stop reason | Status")
        for result in results:
            api_total = result["api_total"] if result["api_total"] is not None else "unavailable"
            print(
                f"{result['hotel']} | {api_total} | {result['collected_unique']} | "
                f"{result['pages_requested']} | {result['stop_reason']} | {result['status']}"
            )
        print()
        print(f"Debug directory: {DEBUG_DIR}")
    finally:
        await close_context(context)


if __name__ == "__main__":
    asyncio.run(main())
