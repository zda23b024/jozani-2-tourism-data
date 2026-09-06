import asyncio
import json
import sys
from copy import deepcopy
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
    result_nodes_for_marker,
    sanitized_tripadvisor_value,
    tripadvisor_restaurants_graphql_payload,
)
from utils.browser_helpers import accept_cookies, close_context, launch_context  # noqa: E402


DEBUG_DIR = OUTPUT_DIR / "debug" / "tripadvisor" / "restaurant_pagination_variants"
DIAGNOSTIC_PROFILE_DIR = DEBUG_DIR / "browser_profile"


def restaurant_ids(response_json: Any) -> list[str]:
    result_nodes = result_nodes_for_marker(response_json, "/Restaurant_Review-")
    cards = extract_graphql_place_cards(result_nodes, "/Restaurant_Review-")
    return [
        str(card.get("location_id") or card.get("url") or "").strip()
        for card in cards
        if card.get("location_id") or card.get("url")
    ]


def variant_payload(base_payload: list[dict[str, Any]], variant: str) -> list[dict[str, Any]]:
    payload = deepcopy(base_payload)
    variables = payload[0]["variables"]
    params = variables["route"]["params"]
    offset = TRIPADVISOR_RESULTS_PER_PAGE
    if variant == "route_params_offset":
        params["offset"] = offset
    elif variant == "top_level_offset":
        variables["offset"] = offset
    elif variant == "both_offsets":
        params["offset"] = offset
        variables["offset"] = offset
    elif variant == "route_params_page":
        params["page"] = 2
    elif variant == "route_params_page_number":
        params["pageNumber"] = 2
    elif variant == "route_params_oa":
        params["oa"] = offset
    elif variant == "restaurants_page_offset":
        variables["route"]["page"] = "Restaurants"
        params["offset"] = offset
    else:
        raise ValueError(f"Unknown variant: {variant}")
    return payload


async def fetch_payload(page, payload: list[dict[str, Any]]) -> dict[str, Any]:
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
    parsed = None
    parse_error = None
    try:
        parsed = json.loads(text)
    except Exception as error:  # noqa: BLE001
        parse_error = str(error)
    return {
        "http_status": response.status,
        "ok": response.ok,
        "parse_error": parse_error,
        "body_preview": None if response.ok else text[:1500],
        "json": parsed,
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
        context = await launch_context(DIAGNOSTIC_PROFILE_DIR, "Tripadvisor restaurant variant diagnostic")

    page = context.pages[0] if context.pages else await context.new_page()
    try:
        await page.goto(TRIPADVISOR_FIND_RESTAURANTS_URL, wait_until="domcontentloaded", timeout=120_000)
        await accept_cookies(page)
        await page.wait_for_timeout(1500)

        page1_payload = await tripadvisor_restaurants_graphql_payload(page, 1)
        page1_response = await fetch_payload(page, page1_payload)
        page1_ids = restaurant_ids(page1_response["json"])
        page1_set = set(page1_ids)

        print("Restaurant page-2 pagination payload variants")
        print()
        print(f"Page 1 restaurants: {len(page1_ids)}")
        print("Variant | status | restaurants | new vs page 1")

        variants = [
            "route_params_offset",
            "top_level_offset",
            "both_offsets",
            "route_params_page",
            "route_params_page_number",
            "route_params_oa",
            "restaurants_page_offset",
        ]
        results = []
        for variant in variants:
            payload = variant_payload(page1_payload, variant)
            response = await fetch_payload(page, payload)
            ids = restaurant_ids(response["json"])
            new_ids = [item for item in ids if item not in page1_set]
            result = {
                "variant": variant,
                "request_variables": sanitized_tripadvisor_value(payload[0].get("variables", {})),
                "http_status": response["http_status"],
                "ok": response["ok"],
                "parse_error": response["parse_error"],
                "body_preview": response["body_preview"],
                "restaurant_count": len(ids),
                "new_vs_page_1": len(new_ids),
                "restaurant_ids": ids,
                "new_restaurant_ids": new_ids,
            }
            results.append(result)
            print(
                f"{variant} | {response['http_status']} | "
                f"{len(ids)} | {len(new_ids)}"
            )

        (DEBUG_DIR / "variants.json").write_text(
            json.dumps(
                {
                    "page_1_ids": page1_ids,
                    "results": results,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print()
        print(f"Debug file: {DEBUG_DIR / 'variants.json'}")
    finally:
        await close_context(context)


if __name__ == "__main__":
    asyncio.run(main())
