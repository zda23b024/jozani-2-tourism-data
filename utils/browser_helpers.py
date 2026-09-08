import json
from typing import Any
from pathlib import Path

from playwright.async_api import BrowserContext, Page, Request, async_playwright

from config.configuration import BROWSER_PROFILE_DIR, HEADLESS


def parse_request_body(request: Request) -> Any:
    try:
        body = request.post_data_json
        if isinstance(body, (dict, list)):
            return body
    except Exception:
        pass
    post_data = request.post_data
    if not post_data:
        return None
    try:
        body = json.loads(post_data)
    except json.JSONDecodeError:
        return None
    return body if isinstance(body, (dict, list)) else None


async def accept_cookies(page: Page) -> None:
    for selector in [
        'button:has-text("Accept all")',
        'button:has-text("Accept")',
        'button:has-text("I agree")',
        'button[id*="accept"]',
        'button[aria-label*="Accept"]',
    ]:
        try:
            button = page.locator(selector).first
            if await button.is_visible(timeout=1500):
                await button.click()
                await page.wait_for_timeout(1000)
                print("Cookie dialog accepted.")
                return
        except Exception:
            continue


async def collect_page_debug(
    page: Page,
    selectors: dict[str, str] | None = None,
    text_limit: int = 3000,
) -> dict[str, Any]:
    selectors = selectors or {}
    try:
        title = await page.title()
    except Exception:
        title = None
    try:
        url = page.url
    except Exception:
        url = None
    try:
        body_text = await page.locator("body").inner_text(timeout=3000)
    except Exception:
        body_text = ""

    counts: dict[str, Any] = {}
    for name, selector in selectors.items():
        try:
            counts[name] = await page.locator(selector).count()
        except Exception as error:
            counts[name] = f"error: {error}"

    lower_text = body_text.lower()
    return {
        "url": url,
        "title": title,
        "body_preview": body_text[:text_limit],
        "body_length": len(body_text),
        "counts": counts,
        "looks_restricted": (
            "access is temporarily restricted" in lower_text
            or "detected unusual activity" in lower_text
            or "automated (bot) activity" in lower_text
        ),
    }


async def build_fetch_headers(request: Request) -> dict[str, str]:
    original_headers = await request.all_headers()
    allowed = {
        "accept",
        "accept-language",
        "apollographql-client-name",
        "apollographql-client-version",
        "content-type",
        "x-booking-context-action-name",
        "x-booking-context-aid",
        "x-booking-csrf-token",
        "x-booking-et-serialized-state",
        "x-booking-pageview-id",
        "x-booking-site-type-id",
        "x-booking-topic",
    }
    headers = {
        name.lower(): value
        for name, value in original_headers.items()
        if name.lower() in allowed
    }
    headers["accept"] = "*/*"
    headers["content-type"] = "application/json"
    return headers


async def fetch_graphql_page(
    page: Page,
    endpoint_url: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> dict[str, Any]:
    result = await page.evaluate(
        """
        async ({url, headers, body}) => {
            const response = await fetch(url, {
                method: "POST",
                headers: headers,
                credentials: "include",
                body: JSON.stringify(body)
            });
            const responseText = await response.text();
            let parsed;
            try { parsed = JSON.parse(responseText); }
            catch (error) { parsed = {parseError: String(error), responseText}; }
            return {ok: response.ok, status: response.status, statusText: response.statusText, data: parsed};
        }
        """,
        {"url": endpoint_url, "headers": headers, "body": body},
    )
    if not result.get("ok"):
        raise RuntimeError(
            f"GraphQL request failed: {result.get('status')} {result.get('statusText')}"
        )
    data = result.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("The website returned an invalid JSON response.")
    return data


async def launch_context(
    profile_dir: str | Path | None = None,
    profile_name: str = "browser",
) -> BrowserContext:
    user_data_dir = Path(profile_dir or BROWSER_PROFILE_DIR)
    user_data_dir.mkdir(parents=True, exist_ok=True)
    print(f"Using {profile_name} profile: {user_data_dir}")
    playwright = await async_playwright().start()
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(user_data_dir),
        headless=HEADLESS,
        viewport={"width": 1440, "height": 1000},
        locale="en-GB",
        args=[
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ],
    )
    context._jozani_playwright = playwright
    return context


async def close_context(context: BrowserContext) -> None:
    playwright = getattr(context, "_jozani_playwright", None)
    await context.close()
    if playwright is not None:
        await playwright.stop()
