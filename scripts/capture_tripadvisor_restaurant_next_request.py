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
    TRIPADVISOR_RESTAURANTS_GRAPHQL_QUERY_ID,
    TRIPADVISOR_RESTAURANTS_URL,
)
from scraper.tripadvisor.scrape_places import sanitized_tripadvisor_value  # noqa: E402
from utils.browser_helpers import accept_cookies, close_context, launch_context  # noqa: E402


DEBUG_DIR = OUTPUT_DIR / "debug" / "tripadvisor" / "restaurant_next_request"
DIAGNOSTIC_PROFILE_DIR = DEBUG_DIR / "browser_profile"
TARGET_URL_PART = "https://www.tripadvisor.com/data/graphql/ids"
START_URLS = [
    ("find_restaurants", TRIPADVISOR_FIND_RESTAURANTS_URL),
    ("restaurants_listing", TRIPADVISOR_RESTAURANTS_URL),
]


def parse_request_body(body: str | None) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"parse_error": "request body is not JSON", "preview": body[:500]}


def matching_operation(payload: Any) -> dict[str, Any] | None:
    operations = payload if isinstance(payload, list) else [payload]
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        query_id = (
            operation.get("extensions", {}).get("preRegisteredQueryId")
            if isinstance(operation.get("extensions"), dict)
            else None
        )
        if query_id == TRIPADVISOR_RESTAURANTS_GRAPHQL_QUERY_ID:
            return operation
    return None


def compact_operation(operation: dict[str, Any] | None) -> dict[str, Any] | None:
    if not operation:
        return None
    variables = operation.get("variables")
    return {
        "preRegisteredQueryId": operation.get("extensions", {}).get("preRegisteredQueryId"),
        "variables": sanitized_tripadvisor_value(variables if isinstance(variables, dict) else {}),
    }


def changed_fields(first: Any, second: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(first, dict) and isinstance(second, dict):
        changes = []
        for key in sorted(set(first) | set(second)):
            child_path = f"{path}.{key}" if path else str(key)
            changes.extend(changed_fields(first.get(key), second.get(key), child_path))
        return changes
    if first != second:
        return [{"path": path or "$", "from": first, "to": second}]
    return []


async def main() -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    captured: list[dict[str, Any]] = []
    page_states: list[dict[str, Any]] = []

    try:
        context = await launch_context(TRIPADVISOR_BROWSER_PROFILE_DIR, "Tripadvisor")
    except PlaywrightError as error:
        if "Opening in existing browser session" not in str(error):
            raise
        print("Tripadvisor browser profile is already in use.")
        print(f"Retrying with diagnostic profile: {DIAGNOSTIC_PROFILE_DIR}")
        context = await launch_context(DIAGNOSTIC_PROFILE_DIR, "Tripadvisor restaurant request capture")

    page = context.pages[0] if context.pages else await context.new_page()

    def on_request(request) -> None:
        if TARGET_URL_PART not in request.url:
            return
        payload = parse_request_body(request.post_data)
        operation = matching_operation(payload)
        if operation is None:
            return
        captured.append(
            {
                "url": request.url,
                "method": request.method,
                "operation": compact_operation(operation),
            }
        )
        print(f"Captured restaurant catalogue request {len(captured)}")

    page.on("request", on_request)
    try:
        selectors = [
            'a[aria-label*="Next" i]',
            'button[aria-label*="Next" i]',
            'a:has-text("Next")',
            'button:has-text("Next")',
            'a[href*="offset=30"]',
            'a[href*="oa30"]',
            '[data-smoke-attr="pagination-next-arrow"]',
        ]
        for label, start_url in START_URLS:
            if len(captured) >= 2:
                break
            await page.goto(start_url, wait_until="domcontentloaded", timeout=120_000)
            await accept_cookies(page)
            await page.wait_for_timeout(4000)
            page_states.append(await page.evaluate(
                """
                ({label}) => {
                    const hrefs = [...document.querySelectorAll('a[href]')]
                        .map((anchor) => anchor.getAttribute('href') || '');
                    const bodyText = (document.body?.innerText || '').replace(/\\s+/g, ' ').trim();
                    return {
                        label,
                        title: document.title || '',
                        current_url: location.href,
                        href_count: hrefs.length,
                        graphql_text_count: (document.documentElement.innerHTML.match(/7c7457de6bd4ad87/g) || []).length,
                        restaurant_href_count: hrefs.filter((href) => href.includes('Restaurant_Review')).length,
                        next_href_count: hrefs.filter((href) => /offset=30|oa30|next/i.test(href)).length,
                        body_preview: bodyText.slice(0, 1000),
                    };
                }
                """,
                {"label": label},
            ))

            for _ in range(8):
                if len(captured) >= 2:
                    break
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(1500)

            for selector in selectors:
                if len(captured) >= 2:
                    break
                try:
                    locator = page.locator(selector).first
                    if await locator.count():
                        await locator.click(timeout=5000)
                        await page.wait_for_timeout(5000)
                except Exception:
                    continue

        first = captured[0]["operation"] if captured else None
        second = captured[1]["operation"] if len(captured) > 1 else None
        changes = changed_fields(first, second) if first and second else []
        output = {
            "captured_count": len(captured),
            "page_states": page_states,
            "requests": captured[:2],
            "changed_fields": changes,
        }
        (DEBUG_DIR / "capture.json").write_text(
            json.dumps(output, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        if len(captured) < 2:
            print("Could not capture a real second restaurant catalogue request.")
            print(f"Debug file: {DEBUG_DIR / 'capture.json'}")
            return

        print()
        print("Changed pagination fields:")
        for change in changes:
            print(f"{change['path']}: {change['from']} -> {change['to']}")
        print()
        print(f"Debug file: {DEBUG_DIR / 'capture.json'}")
    finally:
        await close_context(context)


if __name__ == "__main__":
    asyncio.run(main())
