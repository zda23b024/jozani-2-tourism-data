import asyncio
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
    TRIPADVISOR_FIND_RESTAURANTS_URL,
    TRIPADVISOR_RESTAURANTS_GRAPHQL_URL,
    TRIPADVISOR_RESULTS_PER_PAGE,
)
from scraper.tripadvisor.scrape_places import (  # noqa: E402
    extract_graphql_place_cards,
    normalize_place_card,
    place_metadata_complete,
    sanitized_tripadvisor_value,
    tripadvisor_restaurants_graphql_payload,
)
from utils.browser_helpers import accept_cookies, close_context, launch_context  # noqa: E402


DEBUG_DIR = OUTPUT_DIR / "debug" / "tripadvisor" / "restaurant_pagination"
DIAGNOSTIC_PROFILE_DIR = DEBUG_DIR / "browser_profile"


def page_offset(page_number: int) -> int:
    return (page_number - 1) * TRIPADVISOR_RESULTS_PER_PAGE


def location_key(card: dict[str, Any]) -> str:
    return str(card.get("location_id") or card.get("url") or "").strip()


def response_total(metadata: dict[str, Any]) -> int | None:
    for key in ("totalCount", "totalResults", "total_results", "totalHits", "total_hits"):
        value = metadata.get(key)
        if value in (None, ""):
            continue
        try:
            return int(str(value).replace(",", ""))
        except ValueError:
            continue
    return None


def response_object(response_json: Any) -> dict[str, Any]:
    try:
        value = response_json[0]["data"]["response"]
    except (TypeError, KeyError, IndexError):
        return {}
    return value if isinstance(value, dict) else {}


def restaurant_records(response_json: Any) -> list[dict[str, Any]]:
    restaurants = response_object(response_json).get("restaurants")
    if not isinstance(restaurants, list):
        return []
    return [item for item in restaurants if isinstance(item, dict)]


def response_metadata(response_json: Any) -> dict[str, Any]:
    metadata = response_object(response_json).get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def response_pagination(response_json: Any) -> dict[str, Any]:
    pagination = response_object(response_json).get("pagination")
    return pagination if isinstance(pagination, dict) else {}


def next_cursor(response_json: Any) -> Any:
    metadata = response_metadata(response_json)
    if metadata.get("nextCursor") or metadata.get("next_cursor"):
        return metadata.get("nextCursor") or metadata.get("next_cursor")
    pagination = response_pagination(response_json)
    return pagination.get("nextCursor") or pagination.get("next_cursor")


async def fetch_restaurant_page(page, page_number: int) -> dict[str, Any]:
    payload = await tripadvisor_restaurants_graphql_payload(page, page_number)
    response = await page.context.request.post(
        TRIPADVISOR_RESTAURANTS_GRAPHQL_URL,
        data=json.dumps(payload),
        headers={
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "origin": "https://www.tripadvisor.com",
            "referer": TRIPADVISOR_FIND_RESTAURANTS_URL,
            "sec-fetch-mode": "same-origin",
            "sec-fetch-site": "same-origin",
        },
        timeout=120_000,
    )
    text = await response.text()
    parsed: Any = None
    parse_error = None
    try:
        parsed = json.loads(text)
    except Exception as error:  # noqa: BLE001
        parse_error = str(error)

    records = restaurant_records(parsed) if parsed is not None else []
    cards = extract_graphql_place_cards(records, "/Restaurant_Review-")
    normalized_places = []
    rejected = 0
    for card in cards:
        place = normalize_place_card(card, "restaurants")
        if place:
            normalized_places.append(place)
        else:
            rejected += 1
    metadata = response_metadata(parsed) if parsed is not None else {}
    pagination = response_pagination(parsed) if parsed is not None else {}
    return {
        "request": {
            "url": TRIPADVISOR_RESTAURANTS_GRAPHQL_URL,
            "variables": sanitized_tripadvisor_value(payload[0].get("variables", {})),
            "extensions": sanitized_tripadvisor_value(payload[0].get("extensions", {})),
            "page_number": page_number,
            "offset": page_offset(page_number),
        },
        "response": {
            "http_status": response.status,
            "ok": response.ok,
            "content_type": response.headers.get("content-type", ""),
            "parse_error": parse_error,
            "body_preview": None if response.ok else text[:1500],
            "metadata": sanitized_tripadvisor_value(metadata),
            "pagination": sanitized_tripadvisor_value(pagination),
            "api_total": response_total(metadata),
            "nextCursor": next_cursor(parsed),
            "nextCursor_present": next_cursor(parsed) is not None,
            "raw_nodes": len(records),
            "cards": len(cards),
            "normalized_places": len(normalized_places),
            "rejected_cards": rejected,
            "restaurant_ids": [location_key(card) for card in cards],
            "restaurants": [
                {
                    "name": card.get("name"),
                    "location_id": card.get("location_id"),
                    "url": card.get("url"),
                }
                for card in cards
            ],
        },
        "metadata": metadata,
        "pagination": pagination,
        "cards": cards,
        "normalized_places": normalized_places,
    }


async def main() -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        context = await launch_context(TRIPADVISOR_BROWSER_PROFILE_DIR, "Tripadvisor")
    except PlaywrightError as error:
        if "Opening in existing browser session" not in str(error):
            raise
        print("Tripadvisor browser profile is already in use.")
        print(f"Retrying with diagnostic profile: {DIAGNOSTIC_PROFILE_DIR}")
        context = await launch_context(DIAGNOSTIC_PROFILE_DIR, "Tripadvisor restaurant diagnostic")

    page = context.pages[0] if context.pages else await context.new_page()
    try:
        await page.goto(TRIPADVISOR_FIND_RESTAURANTS_URL, wait_until="domcontentloaded", timeout=120_000)
        await accept_cookies(page)
        await page.wait_for_timeout(1500)

        seen_ids: set[str] = set()
        previous_page_ids: tuple[str, ...] | None = None
        total_unique = 0
        page_number = 1
        stop_reason = "not_started"
        api_total = None

        print("Tripadvisor restaurant catalog pagination diagnostic")
        print()
        print("Page | offset | received | normalized | new | total unique | API total | nextCursor")

        while True:
            result = await fetch_restaurant_page(page, page_number)
            response = result["response"]
            cards = result["cards"]
            normalized_places = result["normalized_places"]
            page_ids = tuple(location_key(card) for card in cards if location_key(card))
            new_ids = [place_id for place_id in page_ids if place_id not in seen_ids]
            for place_id in new_ids:
                seen_ids.add(place_id)
            total_unique = len(seen_ids)
            api_total = response["api_total"] if response["api_total"] is not None else api_total

            diagnostic = {
                "page_number": page_number,
                "offset": page_offset(page_number),
                "new_unique": len(new_ids),
                "total_unique": total_unique,
                "stop_reason_after_page": None,
                "request": result["request"],
                "response": response,
            }
            page_path = DEBUG_DIR / f"page_{page_number}.json"
            page_path.write_text(
                json.dumps(diagnostic, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            print(
                f"{page_number:>4} | {page_offset(page_number):>6} | "
                f"{response['raw_nodes']:>8} | {len(normalized_places):>10} | "
                f"{len(new_ids):>3} | {total_unique:>12} | "
                f"{api_total if api_total is not None else 'unknown'} | "
                f"{'PRESENT' if response['nextCursor_present'] else 'MISSING'}"
            )

            if not response["ok"]:
                stop_reason = f"http_{response['http_status']}"
                break
            if not cards:
                stop_reason = "empty_results"
                break
            if not new_ids:
                stop_reason = "no_new_restaurant_ids"
                break
            if previous_page_ids is not None and page_ids == previous_page_ids:
                stop_reason = "repeated_page_ids"
                break
            previous_page_ids = page_ids
            if place_metadata_complete(result["metadata"], page_offset(page_number), response["raw_nodes"]):
                stop_reason = "metadata_total_reached"
                break
            if response["raw_nodes"] < TRIPADVISOR_RESULTS_PER_PAGE:
                stop_reason = "short_page"
                break
            page_number += 1

        summary = {
            "api_total": api_total,
            "total_unique": total_unique,
            "pages_requested": page_number,
            "stop_reason": stop_reason,
            "pagination_confirmed": stop_reason in {"metadata_total_reached", "short_page", "empty_results"},
            "next_action": (
                "Restaurant pagination is not confirmed because the next page "
                "returned no new restaurant IDs. A real Tripadvisor frontend "
                "continuation request must be captured before production "
                "pagination is changed."
                if stop_reason == "no_new_restaurant_ids"
                else None
            ),
        }
        (DEBUG_DIR / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print()
        print(f"Stop reason: {stop_reason}")
        print(f"Total unique restaurants: {total_unique}")
        print(f"API total: {api_total if api_total is not None else 'unknown'}")
        if summary["next_action"]:
            print(summary["next_action"])
        print(f"Debug directory: {DEBUG_DIR}")
    finally:
        await close_context(context)


if __name__ == "__main__":
    asyncio.run(main())
