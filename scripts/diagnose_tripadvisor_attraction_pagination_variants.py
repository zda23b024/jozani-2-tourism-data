import asyncio
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from playwright.async_api import Error as PlaywrightError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.configuration import (  # noqa: E402
    ADULTS,
    CHECKIN,
    OUTPUT_DIR,
    TRIPADVISOR_ATTRACTIONS_GRAPHQL_QUERY_ID,
    TRIPADVISOR_ATTRACTIONS_GRAPHQL_URL,
    TRIPADVISOR_ATTRACTIONS_SORT,
    TRIPADVISOR_ATTRACTIONS_URL,
    TRIPADVISOR_BROWSER_PROFILE_DIR,
    TRIPADVISOR_GEO_ID,
    TRIPADVISOR_RESULTS_PER_PAGE,
)
from scraper.tripadvisor.scrape_places import (  # noqa: E402
    attraction_card_sections,
    attraction_total_results,
    extract_graphql_place_cards,
    paginated_url,
    sanitized_tripadvisor_value,
    tripadvisor_attractions_graphql_payload,
)
from utils.browser_helpers import accept_cookies, close_context, launch_context  # noqa: E402


DEBUG_DIR = OUTPUT_DIR / "debug" / "tripadvisor" / "attraction_pagination_variants"
DIAGNOSTIC_PROFILE_DIR = DEBUG_DIR / "browser_profile"
CAPTURED_QUERY_ID = "8bec54ff91f21c39"


def page_payload(
    payload: list[dict[str, Any]],
    page_number: int,
    query_id: str,
    filters: list[dict[str, Any]] | list[Any],
) -> list[dict[str, Any]]:
    cloned = deepcopy(payload)
    cloned[0]["extensions"]["preRegisteredQueryId"] = query_id
    route_params = cloned[0]["variables"]["request"]["routeParameters"]
    route_params["filters"] = filters
    if page_number > 1:
        route_params["pagee"] = str((page_number - 1) * TRIPADVISOR_RESULTS_PER_PAGE)
    else:
        route_params.pop("pagee", None)
    return cloned


async def fetch_payload(page, payload: list[dict[str, Any]], page_number: int) -> dict[str, Any]:
    response = await page.context.request.post(
        TRIPADVISOR_ATTRACTIONS_GRAPHQL_URL,
        data=json.dumps(payload),
        headers={
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "origin": "https://www.tripadvisor.com",
            "referer": paginated_url(TRIPADVISOR_ATTRACTIONS_URL, page_number),
            "sec-fetch-mode": "same-origin",
            "sec-fetch-site": "same-origin",
        },
        timeout=120_000,
    )
    text = await response.text()
    parsed = None
    parse_error = None
    try:
        parsed = json.loads(text)
    except Exception as error:  # noqa: BLE001
        parse_error = str(error)
    sections = attraction_card_sections(parsed) if parsed is not None else []
    cards = extract_graphql_place_cards(sections, "/Attraction_Review-")
    return {
        "http_status": response.status,
        "ok": response.ok,
        "parse_error": parse_error,
        "body_preview": None if response.ok else text[:1500],
        "total_results": attraction_total_results(parsed) if parsed is not None else None,
        "card_sections": len(sections),
        "cards": len(cards),
        "attraction_ids": [
            str(card.get("location_id") or card.get("url") or "").strip()
            for card in cards
            if card.get("location_id") or card.get("url")
        ],
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
        context = await launch_context(DIAGNOSTIC_PROFILE_DIR, "Tripadvisor attraction variant diagnostic")

    page = context.pages[0] if context.pages else await context.new_page()
    try:
        await page.goto(TRIPADVISOR_ATTRACTIONS_URL, wait_until="domcontentloaded", timeout=120_000)
        await accept_cookies(page)
        await page.wait_for_timeout(1500)

        filter_cases = {
            "all_attractions_filter": [{"id": "allAttractions", "value": ["true"]}],
            "empty_filters": [],
        }
        query_cases = {
            "configured_query": TRIPADVISOR_ATTRACTIONS_GRAPHQL_QUERY_ID,
            "captured_query": CAPTURED_QUERY_ID,
        }

        print("Attraction catalogue pagination variants")
        print()
        print("Variant | page 1 cards | page 2 cards | new page 2 | API total")
        results = []
        for query_label, query_id in query_cases.items():
            for filter_label, filters in filter_cases.items():
                name = f"{query_label}+{filter_label}"
                payload = await tripadvisor_attractions_graphql_payload(page, 1)
                page1_payload = page_payload(payload, 1, query_id, filters)
                page2_payload = page_payload(payload, 2, query_id, filters)
                page1 = await fetch_payload(page, page1_payload, 1)
                page2 = await fetch_payload(page, page2_payload, 2)
                page1_ids = set(page1["attraction_ids"])
                page2_new = [item for item in page2["attraction_ids"] if item not in page1_ids]
                result = {
                    "variant": name,
                    "query_id": query_id,
                    "page_1_request": sanitized_tripadvisor_value(page1_payload[0]["variables"]),
                    "page_2_request": sanitized_tripadvisor_value(page2_payload[0]["variables"]),
                    "page_1": page1,
                    "page_2": page2,
                    "page_2_new_ids": page2_new,
                }
                results.append(result)
                print(
                    f"{name} | {page1['cards']} | {page2['cards']} | "
                    f"{len(page2_new)} | {page1['total_results']}"
                )

        (DEBUG_DIR / "variants.json").write_text(
            json.dumps({"results": results}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print()
        print(f"Debug file: {DEBUG_DIR / 'variants.json'}")
    finally:
        await close_context(context)


if __name__ == "__main__":
    asyncio.run(main())
