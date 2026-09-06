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
    TRIPADVISOR_RESTAURANTS_URL,
    TRIPADVISOR_RESULTS_PER_PAGE,
)
from scraper.tripadvisor.scrape_places import (  # noqa: E402
    extract_place_cards,
    normalize_place_card,
    paginated_url,
)
from scraper.tripadvisor.scrape_stays import extract_static_cards_from_html, fetch_static_html  # noqa: E402
from utils.browser_helpers import accept_cookies, close_context, launch_context  # noqa: E402


DEBUG_DIR = OUTPUT_DIR / "debug" / "tripadvisor" / "restaurant_html_pagination"
DIAGNOSTIC_PROFILE_DIR = DEBUG_DIR / "browser_profile"
BASE_URLS = [
    ("restaurants_listing", TRIPADVISOR_RESTAURANTS_URL),
    ("find_restaurants", TRIPADVISOR_FIND_RESTAURANTS_URL),
]


def location_key(card: dict[str, Any]) -> str:
    return str(card.get("location_id") or card.get("url") or "").strip()


async def page_diagnostics(page) -> dict[str, Any]:
    return await page.evaluate(
        """
        () => {
            const hrefs = [...document.querySelectorAll('a[href]')]
                .map((anchor) => anchor.getAttribute('href') || '');
            const bodyText = (document.body?.innerText || '').replace(/\\s+/g, ' ').trim();
            return {
                title: document.title || '',
                current_url: location.href,
                href_count: hrefs.length,
                restaurant_href_count: hrefs.filter((href) => href.includes('Restaurant_Review')).length,
                restaurant_text_marker_count: (document.documentElement.innerHTML.match(/Restaurant_Review/g) || []).length,
                body_preview: bodyText.slice(0, 1000),
            };
        }
        """
    )


async def extract_restaurant_page(page, base_label: str, base_url: str, page_number: int) -> dict[str, Any]:
    url = paginated_url(base_url, page_number)
    await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    await accept_cookies(page)
    await page.wait_for_timeout(2500)
    diagnostics = await page_diagnostics(page)
    raw_cards = await extract_place_cards(page, "/Restaurant_Review-")
    method = "browser"
    if not raw_cards:
        html_text = await page.content()
        raw_cards = extract_static_cards_from_html(html_text, "Restaurant_Review-")
        method = "loaded_html"
    if not raw_cards:
        html_text = await fetch_static_html(page, url)
        raw_cards = extract_static_cards_from_html(html_text, "Restaurant_Review-")
        method = "static_fetch"

    normalized = []
    rejected = 0
    for card in raw_cards:
        place = normalize_place_card(card, "restaurants")
        if place:
            normalized.append(place)
        else:
            rejected += 1

    return {
        "page_number": page_number,
        "offset": (page_number - 1) * TRIPADVISOR_RESULTS_PER_PAGE,
        "base_label": base_label,
        "url": url,
        "method": method,
        "page_diagnostics": diagnostics,
        "raw_cards": len(raw_cards),
        "normalized": len(normalized),
        "rejected": rejected,
        "restaurant_ids": [location_key(card) for card in raw_cards if location_key(card)],
        "restaurants": [
            {
                "name": card.get("name"),
                "location_id": card.get("location_id"),
                "url": card.get("url"),
            }
            for card in raw_cards
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
        context = await launch_context(DIAGNOSTIC_PROFILE_DIR, "Tripadvisor restaurant HTML diagnostic")

    page = context.pages[0] if context.pages else await context.new_page()
    try:
        seen_ids: set[str] = set()
        previous_page_ids: tuple[str, ...] | None = None
        stop_reason = "not_started"
        page_number = 1

        print("Tripadvisor restaurant HTML/listing pagination diagnostic")
        print()
        print("Base | page | offset | raw | normalized | new | total unique | method | restaurant hrefs")

        for base_label, base_url in BASE_URLS:
            seen_ids.clear()
            previous_page_ids = None
            page_number = 1
            stop_reason = "not_started"
            while True:
                result = await extract_restaurant_page(page, base_label, base_url, page_number)
                page_ids = tuple(result["restaurant_ids"])
                new_ids = [item for item in page_ids if item not in seen_ids]
                for item in new_ids:
                    seen_ids.add(item)

                result["new_unique"] = len(new_ids)
                result["total_unique"] = len(seen_ids)
                result["stop_reason_after_page"] = None
                (DEBUG_DIR / f"{base_label}_page_{page_number}.json").write_text(
                    json.dumps(result, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

                print(
                    f"{base_label} | {page_number:>4} | {result['offset']:>6} | "
                    f"{result['raw_cards']:>3} | {result['normalized']:>10} | "
                    f"{len(new_ids):>3} | {len(seen_ids):>12} | {result['method']} | "
                    f"{result['page_diagnostics']['restaurant_href_count']}"
                )

                if not page_ids:
                    stop_reason = "empty_results"
                    break
                if not new_ids:
                    stop_reason = "no_new_restaurant_ids"
                    break
                if previous_page_ids is not None and page_ids == previous_page_ids:
                    stop_reason = "repeated_page_ids"
                    break
                previous_page_ids = page_ids
                if result["raw_cards"] < TRIPADVISOR_RESULTS_PER_PAGE:
                    stop_reason = "short_page"
                    break
                page_number += 1

            print(f"{base_label} stop reason: {stop_reason}")
            print()

        summary = {
            "total_unique": len(seen_ids),
            "pages_requested": page_number,
            "stop_reason": stop_reason,
            "pagination_confirmed": stop_reason in {"empty_results", "short_page"},
        }
        (DEBUG_DIR / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print()
        print(f"Stop reason: {stop_reason}")
        print(f"Total unique restaurants: {len(seen_ids)}")
        print(f"Debug directory: {DEBUG_DIR}")
    finally:
        await close_context(context)


if __name__ == "__main__":
    asyncio.run(main())
