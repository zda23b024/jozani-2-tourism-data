import asyncio
import json
import re
from copy import deepcopy
from typing import Any
from urllib.parse import quote_plus

from playwright.async_api import BrowserContext, Page, Request

from config.configuration import (
    CATALOG_ATTRACTION_DESTINATIONS,
    ATTRACTION_REVIEW_DEBUG_DIR,
    ATTRACTIONS_DEST_ID,
    ATTRACTIONS_PER_PAGE,
    ATTRACTIONS_URL,
    ATTRACTION_API_CAPTURE_TIMEOUT_SECONDS,
    CHECKIN,
    CHECKOUT,
    MAX_ATTRACTION_PAGES,
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
    join_values,
    nested_get,
    normalize_booking_url,
    safe_filename,
    stable_review_id,
)
from scraper.booking.scrape_reviews import (
    find_review_items,
    normalize_review,
    review_page_numbers,
    review_cutoff_date,
    should_collect_review,
)


def is_attraction_search_request(request: Request) -> bool:
    if "/dml/graphql" not in request.url or request.method != "POST":
        return False
    body = parse_request_body(request)
    if not body:
        return False
    operation_name = str(body.get("operationName") or "")
    query = str(body.get("query") or "")
    input_data = nested_get(body, "variables", "input") or {}
    return (
        operation_name == "SearchResultsProducts"
        and "attractionsProduct" in query
        and "products" in query
        and int(input_data.get("limit") or 0) > 0
    )


def is_attraction_review_request(request: Request) -> bool:
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
        and "attractionsproduct" in combined
        and "searchproducts" not in combined
    )


def remove_catalog_attraction_date_filters(value: Any) -> None:
    date_keys = {
        "filterbystartdate",
        "filterbyenddate",
        "startdate",
        "enddate",
        "start_date",
        "end_date",
        "date",
    }
    if isinstance(value, dict):
        for key in list(value.keys()):
            if str(key).lower() in date_keys:
                value.pop(key, None)
                continue
            remove_catalog_attraction_date_filters(value[key])
    elif isinstance(value, list):
        for child in value:
            remove_catalog_attraction_date_filters(child)


def attraction_search_url(dest_id: str, catalog_mode: bool) -> str:
    if catalog_mode:
        return (
            "https://www.booking.com/attractions/searchresults.en-gb.html"
            "?selected_currency=TZS"
            "&source=search_box"
            f"&dest_id={quote_plus(dest_id)}"
        )
    return ATTRACTIONS_URL


def attraction_dedupe_key(attraction: dict[str, Any]) -> str:
    attraction_id = attraction.get("attraction_id")
    if attraction_id not in (None, ""):
        return f"id:{attraction_id}"
    return str(attraction.get("name") or "").strip().lower()


def attraction_source_place_id(attraction: dict[str, Any]) -> str:
    value = attraction.get("attraction_id")
    if value not in (None, ""):
        return str(value)
    return str(attraction.get("name") or "").strip().lower().replace(" ", "_")


def attraction_place_id(source_place_id: str) -> str:
    return f"booking:attraction:place:{source_place_id}"


def attraction_place_source_id(source_place_id: str) -> str:
    return f"booking:attraction:listing:{source_place_id}"


def prepare_attraction_review(review: dict[str, Any], attraction: dict[str, Any]) -> dict[str, Any]:
    source_place_id = attraction_source_place_id(attraction)
    return {
        **review,
        "source": "booking",
        "source_place_id": source_place_id,
        "place_id": attraction_place_id(source_place_id),
        "place_source_id": attraction_place_source_id(source_place_id),
    }


async def wait_for_attraction_request(
    page: Page,
    attractions_url: str,
) -> Request | None:
    captured_request = None
    request_found = asyncio.Event()

    async def request_handler(request: Request) -> None:
        nonlocal captured_request
        if captured_request is None and is_attraction_search_request(request):
            captured_request = request
            request_found.set()
            print("Captured the browser-generated attractions API request.")

    page.on("request", request_handler)
    await page.goto(attractions_url, wait_until="domcontentloaded", timeout=120_000)
    await accept_cookies(page)

    print()
    print("Attractions page opened.")
    print("Complete any normal verification shown by Booking.com.")
    print("Wait until attraction cards appear.")
    print()

    for attempt in range(4):
        if request_found.is_set():
            break
        try:
            await page.wait_for_timeout(5000)
            await page.evaluate(
                'window.scrollTo({top: document.body.scrollHeight, behavior: "smooth"})'
            )
            await page.wait_for_timeout(2500)
            if request_found.is_set():
                break
            print(
                "Still waiting for an attractions API request "
                f"after browser nudge {attempt + 1}/4..."
            )
        except Exception:
            continue

    try:
        print(
            "Final wait for attractions API request: "
            f"{ATTRACTION_API_CAPTURE_TIMEOUT_SECONDS} seconds..."
        )
        await asyncio.wait_for(
            request_found.wait(),
            timeout=ATTRACTION_API_CAPTURE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        pass
    finally:
        try:
            page.remove_listener("request", request_handler)
        except Exception:
            pass

    return captured_request


async def wait_for_attraction_review_request(
    page: Page,
    attraction: dict[str, Any],
) -> Request | None:
    captured_request = None
    request_found = asyncio.Event()

    async def request_handler(request: Request) -> None:
        nonlocal captured_request
        if captured_request is None and is_attraction_review_request(request):
            captured_request = request
            request_found.set()
            print("  Review panel opened; checking structured review data.")

    page.on("request", request_handler)
    try:
        url = attraction.get("property_url")
        if not url:
            return None
        await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        await accept_cookies(page)
        await page.wait_for_timeout(2500)
        page_title = await page.title()
        if is_bad_attraction_landing_page(page.url, page_title):
            print(f"  Skipping invalid attraction page: {page_title} | {page.url}")
            return None

        for selector in [
            'button:has-text("Reviews")',
            'a:has-text("Reviews")',
            'button:has-text("reviews")',
            'a:has-text("reviews")',
            'button:has-text("Guest reviews")',
            'a:has-text("Guest reviews")',
            'text=/\\d+\\s+reviews/i',
            '[aria-label*="review" i]',
            '[data-testid*="review"]',
        ]:
            if request_found.is_set():
                break
            try:
                target = page.locator(selector).first
                if await target.is_visible(timeout=1000):
                    await target.click()
                    await page.wait_for_timeout(2500)
            except Exception:
                continue

        for _ in range(3):
            if request_found.is_set():
                break
            await page.evaluate(
                'window.scrollTo({top: document.body.scrollHeight, behavior: "smooth"})'
            )
            await page.wait_for_timeout(2000)

        try:
            await asyncio.wait_for(request_found.wait(), timeout=15)
        except asyncio.TimeoutError:
            pass
        return captured_request
    finally:
        try:
            page.remove_listener("request", request_handler)
        except Exception:
            pass


def clean_visible_review_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def is_bad_attraction_landing_page(url: Any, title: Any, body_text: Any = "") -> bool:
    combined = " ".join(
        str(value or "").lower()
        for value in [url, title, body_text[:500] if isinstance(body_text, str) else ""]
    )
    bad_markers = [
        "viator terms",
        "terms & conditions",
        "/attractions/terms",
        "privacy statement",
        "/attractions/privacy",
        "help centre",
        "/attractions/help",
    ]
    return any(marker in combined for marker in bad_markers)


def parse_price_amount(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value)
    match = re.search(r"[\d,.]+", text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def recursive_first_number(value: Any, key_names: set[str]) -> float | None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if key_text in key_names:
                parsed = parse_price_amount(child)
                if parsed is not None:
                    return parsed
            parsed = recursive_first_number(child, key_names)
            if parsed is not None:
                return parsed
    elif isinstance(value, list):
        for child in value:
            parsed = recursive_first_number(child, key_names)
            if parsed is not None:
                return parsed
    return None


def recursive_first_currency(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if key_text in {"currency", "currencycode", "selectedcurrency"}:
                text = str(child or "").strip().upper()
                if text:
                    return "USD" if text == "US$" else text[:3]
            found = recursive_first_currency(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = recursive_first_currency(child)
            if found:
                return found
    return None


def parse_review_count(value: Any) -> int | None:
    if value in (None, ""):
        return None
    match = re.search(r"([\d,]+)\s+reviews?", str(value), flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_review_score(value: Any) -> float | None:
    if value in (None, ""):
        return None
    match = re.search(
        r"\b(\d+(?:\.\d+)?)\b\s*(?:Exceptional|Superb|Excellent|Very good|Good)",
        str(value),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def merge_detail_text(existing: Any, new_value: Any, separator: str = "; ") -> str | None:
    values = []
    for value in [existing, new_value]:
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            values.extend(str(item).strip() for item in value)
        else:
            values.extend(str(item).strip() for item in str(value).split(separator))
    cleaned = [value for value in values if value]
    return separator.join(dict.fromkeys(cleaned)) if cleaned else None


async def scrape_attraction_detail_page(
    page: Page,
    attraction: dict[str, Any],
) -> dict[str, Any]:
    url = attraction.get("property_url")
    if not url:
        return {}

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        await accept_cookies(page)
        await page.wait_for_timeout(2500)
        page_title = await page.title()
        if is_bad_attraction_landing_page(page.url, page_title):
            print(f"  Invalid attraction detail URL opened: {page_title} | {page.url}")
            return {"property_url": None}
        await page.evaluate(
            'window.scrollTo({top: Math.min(document.body.scrollHeight, 4500), behavior: "smooth"})'
        )
        await page.wait_for_timeout(1500)
    except Exception as error:
        print(f"  Attraction detail page failed for {attraction.get('name')}: {error}")
        return {}

    try:
        data = await page.evaluate(
            """
            () => {
                const text = (el) => (el?.innerText || el?.textContent || '').trim();
                const unique = (items) => [...new Set(items.map(v => (v || '').trim()).filter(Boolean))];
                const pickText = (selectors) => {
                    for (const selector of selectors) {
                        const value = text(document.querySelector(selector));
                        if (value) return value;
                    }
                    return null;
                };
                const bodyText = document.body?.innerText || '';
                const lines = unique(
                    bodyText.split('\\n').map(line => line.trim())
                ).filter(line => line.length >= 3 && line.length <= 220);
                const breadcrumbs = unique(
                    [...document.querySelectorAll('nav a, [aria-label*="breadcrumb" i] a')]
                        .map(text)
                );
                const images = unique(
                    [...document.images]
                        .map(img => img.currentSrc || img.src || img.getAttribute('data-src'))
                        .filter(src => src && /^https?:/.test(src))
                );
                const title = pickText(['h1', '[data-testid*="title"]']);
                const subtitle = pickText([
                    '[data-testid*="subtitle"]',
                    '[data-testid*="description"]',
                    'main p'
                ]);
                const description = pickText([
                    '[data-testid*="description"]',
                    '[data-testid*="overview"]',
                    '[data-testid*="about"]',
                    'section'
                ]);
                const featureLines = lines.filter(line =>
                    /free cancellation|duration|guide|pickup|mobile ticket|instant confirmation|included|language/i.test(line)
                ).slice(0, 30);
                const cancellationLine = lines.find(line => /cancellation/i.test(line)) || null;
                return {
                    title,
                    subtitle,
                    description,
                    bodyText,
                    images,
                    breadcrumbs,
                    featureLines,
                    cancellationLine
                };
            }
            """
        )
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}

    body_text = clean_visible_review_text(str(data.get("bodyText") or ""))
    if is_bad_attraction_landing_page(page.url, data.get("title"), body_text):
        print(f"  Invalid attraction detail content skipped: {data.get('title')} | {page.url}")
        return {"property_url": None}

    images = data.get("images") if isinstance(data.get("images"), list) else []
    breadcrumbs = data.get("breadcrumbs") if isinstance(data.get("breadcrumbs"), list) else []
    feature_lines = data.get("featureLines") if isinstance(data.get("featureLines"), list) else []
    existing_photos = attraction.get("photos") or []
    detail_photos = list(dict.fromkeys([*existing_photos, *images]))

    price_match = re.search(
        r"(?:From\s+)?(TZS|USD|US\$|EUR|GBP)\s*([\d,.]+)",
        body_text,
        flags=re.IGNORECASE,
    )
    raw_value = attraction.get("raw") or {}
    if not isinstance(raw_value, dict):
        raw_value = {"search_payload": raw_value}
    raw_detail = {
        "detail_url": url,
        "title": data.get("title"),
        "subtitle": data.get("subtitle"),
        "description": data.get("description"),
        "breadcrumbs": breadcrumbs,
        "feature_lines": feature_lines,
        "cancellation_line": data.get("cancellationLine"),
    }

    detail = {
        "name": attraction.get("name"),
        "description_summary": first_nonempty(
            attraction.get("description_summary"),
            data.get("subtitle"),
        ),
        "description": first_nonempty(
            attraction.get("description"),
            data.get("description"),
            data.get("subtitle"),
        ),
        "display_location": first_nonempty(
            attraction.get("display_location"),
            " > ".join(breadcrumbs[-3:]) if breadcrumbs else None,
        ),
        "review_score": first_nonempty(
            attraction.get("review_score"),
            parse_review_score(body_text),
        ),
        "review_count": first_nonempty(
            attraction.get("review_count"),
            parse_review_count(body_text),
        ),
        "photos": detail_photos,
        "photo_url": first_nonempty(attraction.get("photo_url"), detail_photos[0] if detail_photos else None),
        "features": merge_detail_text(attraction.get("features"), feature_lines),
        "free_cancellation": first_nonempty(
            attraction.get("free_cancellation"),
            "free cancellation" in body_text.lower(),
        ),
        "cancellation_policy": first_nonempty(
            attraction.get("cancellation_policy"),
            data.get("cancellationLine"),
        ),
        "raw": {**raw_value, "detail_page": raw_detail},
    }

    if price_match:
        detail["currency"] = "USD" if price_match.group(1).upper() == "US$" else price_match.group(1).upper()
        detail["price"] = first_nonempty(
            attraction.get("price"),
            parse_price_amount(price_match.group(2)),
        )

    return {key: value for key, value in detail.items() if value not in (None, "", [], {})}


async def enrich_attractions_with_detail_pages(
    context: BrowserContext,
    attractions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not attractions:
        return attractions

    print()
    print("=" * 60)
    print("ENRICHING ATTRACTION DETAIL PAGES")
    print("=" * 60)
    page = await context.new_page()
    try:
        enriched = []
        for index, attraction in enumerate(attractions, start=1):
            print(
                f"[{index}/{len(attractions)}] Detail: "
                f"{attraction.get('name') or attraction.get('attraction_id')}"
            )
            details = await scrape_attraction_detail_page(page, attraction)
            enriched.append({**attraction, **details})
            await page.wait_for_timeout(800)
        return enriched
    finally:
        await page.close()


async def visible_attraction_review_from_page(
    page: Page,
    attraction: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        data = await page.evaluate(
            """
            () => {
                const cards = Array.from(document.querySelectorAll('div, section, article'));
                const card = cards.find((node) => {
                    const text = (node.innerText || '').trim();
                    return text.includes('What guests loved most') && text.length < 2500;
                });
                if (!card) return null;
                const lines = (card.innerText || '')
                    .split('\\n')
                    .map((line) => line.trim())
                    .filter(Boolean)
                    .filter((line) => !/^\\d+(\\.\\d+)?$/.test(line))
                    .filter((line) => !/^reviews?$/i.test(line))
                    .filter((line) => !/^exceptional|superb|good|fabulous$/i.test(line));
                const headingIndex = lines.findIndex((line) => /What guests loved most/i.test(line));
                const useful = headingIndex >= 0 ? lines.slice(headingIndex + 1) : lines;
                const reviewerName = useful[0] || null;
                const reviewText = useful.slice(1).join(' ') || null;
                return {reviewerName, reviewText, rawText: lines.join('\\n')};
            }
            """
        )
    except Exception:
        return None

    if not isinstance(data, dict):
        return None
    review_text = clean_visible_review_text(str(data.get("reviewText") or ""))
    reviewer_name = clean_visible_review_text(str(data.get("reviewerName") or ""))
    if not review_text or len(review_text) < 10:
        return None

    source_place_id = attraction_source_place_id(attraction)
    return prepare_attraction_review(
        {
            "review_id": f"visible:{source_place_id}:{reviewer_name}:{review_text[:80]}",
            "hotel_id": source_place_id,
            "reviewer_name": reviewer_name or None,
            "reviewer_country": None,
            "review_score": attraction.get("review_score"),
            "review_title": "What guests loved most",
            "review_text": review_text,
            "positive_text": review_text,
            "negative_text": None,
            "review_date": CHECKIN,
            "stayed_date": None,
            "room_name": None,
            "language": None,
            "response_id": None,
            "response_text": None,
            "response_date": None,
            "responder_name": None,
            "responder_role": None,
        },
        attraction,
    )


async def visible_attraction_review_list_from_page(
    page: Page,
    attraction: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        raw_reviews = await page.evaluate(
            """
            () => {
                const text = (el) => (el?.innerText || el?.textContent || '').trim();
                const roots = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], aside, section, div'));
                const reviewRoot = roots.find((node) => {
                    const value = text(node);
                    return /Reviews/i.test(value)
                        && /Search reviews|Sort by|Filter by|User ratings/i.test(value)
                        && value.length < 20000;
                });
                if (!reviewRoot) return [];

                const nodes = Array.from(reviewRoot.querySelectorAll('article, [role="listitem"], [data-testid*="review"], div'));
                const candidates = nodes
                    .map((node) => {
                        const lines = text(node)
                            .split('\\n')
                            .map((line) => line.trim())
                            .filter(Boolean);
                        return {node, lines, value: lines.join('\\n')};
                    })
                    .filter((item) => {
                        const value = item.value;
                        if (value.length < 45 || value.length > 1600) return false;
                        if (/Search reviews|Sort by|Filter by|User ratings|Review score|Time of year|Language/i.test(value)) return false;
                        return /Posted\\s+.+\\s+on\\s+Viator/i.test(value)
                            || item.lines.some((line) => line.length >= 45 && /\\w+\\s+\\w+/.test(line));
                    });

                const minimal = candidates.filter((item) => {
                    return !candidates.some((other) => other !== item && item.node.contains(other.node));
                });

                return minimal.slice(0, 25).map((item) => {
                    const lines = item.lines
                        .filter((line) => !/^\\d+(\\.\\d+)?$/.test(line))
                        .filter((line) => !/^(Reviews|Fabulous|Exceptional|Superb|Excellent|Very good|Good)$/i.test(line))
                        .filter((line) => !/^Posted\\s+.+\\s+on\\s+Viator$/i.test(line));
                    const postedLine = item.lines.find((line) => /^Posted\\s+.+\\s+on\\s+Viator$/i.test(line)) || null;
                    const reviewerName = lines.find((line) => line.length > 1 && line.length <= 80) || null;
                    const reviewText = lines
                        .filter((line) => line !== reviewerName)
                        .filter((line) => line.length >= 20)
                        .join(' ');
                    const dateMatch = postedLine ? postedLine.match(/^Posted\\s+(.+?)\\s+on\\s+Viator$/i) : null;
                    return {reviewerName, reviewText, reviewDate: dateMatch ? dateMatch[1] : null, rawText: item.value};
                });
            }
            """
        )
    except Exception:
        return []

    if not isinstance(raw_reviews, list):
        return []

    source_place_id = attraction_source_place_id(attraction)
    reviews = []
    for item in raw_reviews:
        if not isinstance(item, dict):
            continue
        review_text = clean_visible_review_text(str(item.get("reviewText") or ""))
        reviewer_name = clean_visible_review_text(str(item.get("reviewerName") or ""))
        if not review_text or len(review_text) < 20:
            continue
        reviews.append(
            prepare_attraction_review(
                {
                    "review_id": f"visible-list:{source_place_id}:{reviewer_name}:{review_text[:80]}",
                    "hotel_id": source_place_id,
                    "reviewer_name": reviewer_name or None,
                    "reviewer_country": None,
                    "review_score": attraction.get("review_score"),
                    "review_title": "Attraction review",
                    "review_text": review_text,
                    "positive_text": review_text,
                    "negative_text": None,
                    "review_date": item.get("reviewDate") or CHECKIN,
                    "stayed_date": None,
                    "room_name": None,
                    "language": None,
                    "response_id": None,
                    "response_text": None,
                    "response_date": None,
                    "responder_name": None,
                    "responder_role": None,
                },
                attraction,
            )
        )
    return reviews


async def scrape_visible_attraction_review_cards(
    page: Page,
    attraction: dict[str, Any],
    existing_source_review_ids: set[str],
) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    async def add_current_card() -> None:
        visible_reviews = await visible_attraction_review_list_from_page(page, attraction)
        if not visible_reviews:
            single_review = await visible_attraction_review_from_page(page, attraction)
            visible_reviews = [single_review] if single_review else []
        for review in visible_reviews:
            source_review_id = stable_review_id(review)
            if source_review_id in seen_ids:
                continue
            seen_ids.add(source_review_id)
            reviews.append(review)

    await add_current_card()

    for _ in range(12):
        clicked = False
        for selector in [
            'button[aria-label="Next"]',
            'button:has-text("›")',
            'button:has-text(">")',
            '[role="button"][aria-label="Next"]',
        ]:
            try:
                target = page.locator(selector).last
                if await target.is_visible(timeout=600) and await target.is_enabled(timeout=600):
                    await target.click()
                    await page.wait_for_timeout(800)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            break
        before = len(reviews)
        await add_current_card()
        if len(reviews) == before:
            continue

    print(f"  Visible attraction reviews collected: {len(reviews)}")
    return reviews


async def scrape_visible_attraction_review_cards(
    page: Page,
    attraction: dict[str, Any],
    existing_source_review_ids: set[str],
) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_content_keys: set[str] = set()

    async def add_current_cards() -> int:
        visible_reviews = await visible_attraction_review_list_from_page(page, attraction)
        if not visible_reviews:
            single_review = await visible_attraction_review_from_page(page, attraction)
            visible_reviews = [single_review] if single_review else []

        added = 0
        for review in visible_reviews:
            source_review_id = stable_review_id(review)
            content_key = attraction_review_content_key(review)
            if (
                source_review_id in seen_ids
                or content_key in seen_content_keys
            ):
                continue
            seen_ids.add(source_review_id)
            seen_content_keys.add(content_key)
            reviews.append(review)
            added += 1
        return added

    await add_current_cards()

    next_selectors = [
        'button[aria-label="Next"]',
        'button[aria-label*="next" i]',
        '[role="button"][aria-label="Next"]',
        '[role="button"][aria-label*="next" i]',
        'button:has-text("›")',
        'button:has-text(">")',
        'button:has-text("Next")',
        'a[aria-label*="next" i]',
    ]
    stale_clicks = 0

    for click_index in range(60):
        clicked = False
        before_count = len(reviews)
        before_keys = set(seen_content_keys)

        for selector in next_selectors:
            try:
                target = page.locator(selector).last
                if not await target.is_visible(timeout=700):
                    continue
                if not await target.is_enabled(timeout=700):
                    continue
                disabled = await target.evaluate(
                    """
                    (node) => Boolean(
                        node.disabled ||
                        node.getAttribute('aria-disabled') === 'true' ||
                        node.closest('[aria-disabled="true"]')
                    )
                    """
                )
                if disabled:
                    continue
                await target.click()
                await page.wait_for_timeout(1200)
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            try:
                await page.evaluate(
                    """
                    () => {
                        const dialog = document.querySelector('[role="dialog"], [aria-modal="true"]');
                        const target = dialog || document.scrollingElement || document.documentElement;
                        target.scrollBy({top: 700, behavior: 'smooth'});
                    }
                    """
                )
                await page.wait_for_timeout(900)
                if await add_current_cards():
                    stale_clicks = 0
                    continue
            except Exception:
                pass
            break

        for _ in range(5):
            added = await add_current_cards()
            if added or seen_content_keys != before_keys:
                break
            await page.wait_for_timeout(500)

        if len(reviews) == before_count:
            stale_clicks += 1
        else:
            stale_clicks = 0

        if stale_clicks >= 4:
            print(
                "  Visible review carousel stopped after "
                f"{click_index + 1} clicks with no new reviews."
            )
            break

    print(f"  Visible attraction reviews collected: {len(reviews)}")
    if not reviews:
        await save_attraction_review_debug(page, attraction)
    return reviews


def photo_url(photo: Any) -> str | None:
    if isinstance(photo, str):
        return photo
    if not isinstance(photo, dict):
        return None
    return first_nonempty(
        photo.get("hereProductPageDesktop"),
        photo.get("gallery"),
        photo.get("small"),
        photo.get("hereProductPageMobile"),
        photo.get("url"),
    )


def label_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return first_nonempty(value.get("label"), value.get("text"), value.get("name"))
    return None


def labels_from_list(values: Any) -> str | None:
    if not isinstance(values, list):
        return None
    return join_values(
        [
            label_text(value)
            for value in values
            if label_text(value)
        ]
    )


def extract_address(product: dict[str, Any]) -> dict[str, Any]:
    addresses = product.get("addresses") or {}
    for key in ["attraction", "meeting", "departure", "arrival", "entrance", "pickup"]:
        address = addresses.get(key)
        if isinstance(address, dict):
            return address
    return {}


def extract_price(product: dict[str, Any]) -> dict[str, Any]:
    price = first_nonempty(
        product.get("representativePrice"),
        product.get("offersRepresentativePrice"),
        product.get("price"),
        product.get("displayPrice"),
        product.get("pricing"),
    )
    if not isinstance(price, dict):
        parsed_text_price = parse_price_amount(price)
        return {
            "price": parsed_text_price,
            "currency": recursive_first_currency(product),
        }
    return {
        "price": first_nonempty(
            price.get("chargeAmount"),
            price.get("publicAmount"),
            price.get("amount"),
            price.get("value"),
            price.get("finalAmount"),
            price.get("grossAmount"),
            price.get("displayAmount"),
            nested_get(price, "amount", "value"),
            recursive_first_number(
                price,
                {
                    "chargeamount",
                    "publicamount",
                    "amount",
                    "value",
                    "finalamount",
                    "grossamount",
                    "displayamount",
                },
            ),
        ),
        "currency": first_nonempty(
            price.get("currency"),
            price.get("currencyCode"),
            recursive_first_currency(price),
            recursive_first_currency(product),
        ),
    }


def extract_reviews(product: dict[str, Any]) -> dict[str, Any]:
    stats = product.get("reviewsStats") or {}
    combined = stats.get("combinedNumericStats") or {}
    return {
        "review_score": first_nonempty(
            combined.get("average"),
            stats.get("percentage"),
        ),
        "review_count": first_nonempty(
            combined.get("total"),
            stats.get("allReviewsCount"),
        ),
    }


def extract_taxonomy(product: dict[str, Any]) -> dict[str, Any]:
    taxonomy = product.get("taxonomy") or {}
    type_data = taxonomy.get("type") or {}
    categories = taxonomy.get("categories") or []
    tags = taxonomy.get("tags") or []
    return {
        "type_label": label_text(type_data),
        "type_slug": type_data.get("slug") if isinstance(type_data, dict) else None,
        "category_labels": labels_from_list(categories),
        "tag_labels": labels_from_list(tags),
    }


def find_attraction_url(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_name = str(key).lower()
            if key_name in {
                "url",
                "uri",
                "href",
                "deeplink",
                "canonicalurl",
                "weburl",
                "producturl",
            }:
                normalized = normalize_booking_url(child)
                if is_attraction_detail_url(normalized):
                    return normalized
            found = find_attraction_url(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_attraction_url(child)
            if found:
                return found
    elif isinstance(value, str):
        normalized = normalize_booking_url(value)
        if is_attraction_detail_url(normalized):
            return normalized
    return None


def is_attraction_detail_url(url: Any) -> bool:
    normalized = normalize_booking_url(url)
    if not normalized:
        return False
    lowered = normalized.lower()
    if "/attractions/tz/" not in lowered:
        return False
    blocked_parts = [
        "viator-terms",
        "terms-and-conditions",
        "/attractions/content/",
        "/attractions/terms",
        "/attractions/searchresults",
        "/attractions/index",
        "/attractions/help",
        "/attractions/privacy",
        "/attractions/city/",
        "/attractions/country/",
    ]
    if any(part in lowered for part in blocked_parts):
        return False
    return ".html" in lowered


def fallback_attraction_url(product: dict[str, Any]) -> str:
    product_id = str(product.get("id") or "").strip()
    slug = str(product.get("slug") or "").strip().strip("/")
    if not slug:
        slug = safe_filename(product.get("name")).replace("_", "-")

    path_part = slug
    if product_id and slug and not slug.lower().startswith(product_id.lower()):
        path_part = f"{product_id.lower()}-{slug}"
    elif product_id and not slug:
        path_part = product_id.lower()

    return (
        "https://www.booking.com/attractions/tz/"
        f"{quote_plus(path_part)}.html"
        f"?selected_currency=TZS&source=searchresults-product-card"
        f"&start_date={quote_plus(CHECKIN)}&end_date={quote_plus(CHECKOUT)}"
        f"&date={quote_plus(CHECKIN)}&ufi={quote_plus(ATTRACTIONS_DEST_ID)}"
    )


def normalize_attraction(product: dict[str, Any]) -> dict[str, Any]:
    address = extract_address(product)
    taxonomy = extract_taxonomy(product)
    duration = first_nonempty(product.get("duration"), product.get("typicalDuration"), {})
    if not isinstance(duration, dict):
        duration = {}
    cancellation = product.get("cancellationPolicy") or {}
    price = extract_price(product)
    reviews = extract_reviews(product)
    primary_photo = photo_url(product.get("primaryPhoto"))

    return {
        "attraction_id": product.get("id"),
        "name": product.get("name"),
        "description": product.get("description"),
        "description_summary": product.get("shortDescription"),
        "property_url": find_attraction_url(product) or fallback_attraction_url(product),
        "address": address.get("address"),
        "city": first_nonempty(address.get("city"), nested_get(product, "ufiDetails", "bCityName")),
        "country_code": address.get("country"),
        "latitude": address.get("latitude"),
        "longitude": address.get("longitude"),
        "display_location": first_nonempty(
            address.get("instructions"),
            nested_get(product, "ufiDetails", "bInCityName"),
        ),
        "review_score": reviews["review_score"],
        "review_count": reviews["review_count"],
        "photo_url": primary_photo,
        "photos": [
            url
            for url in [primary_photo]
            + [photo_url(photo) for photo in product.get("photos") or []]
            if url
        ],
        "price": price["price"],
        "currency": price["currency"],
        "available": product.get("isBookable"),
        "available_from": first_nonempty(
            product.get("availableFrom"),
            product.get("availableFromSchedule"),
        ),
        "activity_type": taxonomy["type_label"],
        "activity_type_slug": taxonomy["type_slug"],
        "category_labels": taxonomy["category_labels"],
        "tag_labels": taxonomy["tag_labels"],
        "duration_minutes": first_nonempty(duration.get("value"), duration.get("min")),
        "duration_label": duration.get("label"),
        "free_cancellation": cancellation.get("hasFreeCancellation"),
        "cancellation_policy": first_nonempty(
            cancellation.get("message"),
            cancellation.get("label"),
        ),
        "booking_required": product.get("isBookable"),
        "guided_tour": bool(product.get("guideSupportedLanguagesLabels")),
        "family_friendly": bool(nested_get(product, "additionalBookingInfo", "freeForChildren")),
        "best_visit_time": product.get("availableFrom"),
        "badges": join_values(
            [
                labels_from_list(product.get("labels")),
                label_text(product.get("primaryLabel")),
                labels_from_list(product.get("flags")),
                labels_from_list(product.get("highlights")),
            ]
        ),
        "features": join_values(
            [
                labels_from_list(product.get("uniqueSellingPoints")),
                labels_from_list(product.get("whatsIncluded")),
                labels_from_list(product.get("notIncluded")),
                labels_from_list(product.get("healthSafety")),
                labels_from_list(product.get("accessibility")),
            ]
        ),
        "operated_by": product.get("operatedBy"),
        "supplier_name": nested_get(product, "supplierInfo", "details", "name"),
        "raw": product,
    }


def extract_products(payload: dict[str, Any]) -> list[dict[str, Any]]:
    products = nested_get(
        payload,
        "data",
        "attractionsProduct",
        "searchProducts",
        "products",
    )
    if not isinstance(products, list):
        return []
    return [
        normalize_attraction(product)
        for product in products
        if isinstance(product, dict)
    ]


def has_next_page(payload: dict[str, Any]) -> bool:
    return bool(
        nested_get(
            payload,
            "data",
            "attractionsProduct",
            "searchProducts",
            "pagination",
            "hasNextPage",
        )
    )


def attraction_review_total(payload: dict[str, Any]) -> int | None:
    value = nested_get(
        payload,
        "data",
        "attractionsProduct",
        "getReviewsV3",
        "total",
    )
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def attraction_review_content_key(review: dict[str, Any]) -> str:
    return json.dumps(
        [
            review.get("reviewer_name"),
            review.get("review_date"),
            review.get("review_text"),
            review.get("positive_text"),
            review.get("negative_text"),
        ],
        ensure_ascii=False,
        sort_keys=True,
    )


def prepare_attraction_review_request_body(body: dict[str, Any], page_number: int) -> None:
    input_data = nested_get(body, "variables", "input")
    if not isinstance(input_data, dict):
        return

    page_size = REVIEWS_PER_PAGE
    pagination = input_data.get("pagination")
    if isinstance(pagination, dict):
        try:
            page_size = max(page_size, int(pagination.get("pageSize") or page_size))
        except (TypeError, ValueError):
            page_size = REVIEWS_PER_PAGE

    filters = input_data.get("filterBy")
    if isinstance(filters, list):
        input_data["filterBy"] = [
            item
            for item in filters
            if not (
                isinstance(item, dict)
                and str(item.get("filterType") or "").lower()
                in {"score_range", "language"}
            )
        ]

    input_data["pagination"] = {
        "page": page_number,
        "pageSize": page_size,
    }
    input_data["sortBy"] = "newest"
    input_data.pop("offset", None)
    input_data.pop("skip", None)
    input_data.pop("page", None)
    input_data.pop("limit", None)
    input_data.pop("rowsPerPage", None)


async def save_attraction_review_debug(page: Page, attraction: dict[str, Any]) -> None:
    try:
        data = await page.evaluate(
            """
            () => {
                const text = (el) => (el?.innerText || el?.textContent || '').trim();
                const buttons = Array.from(document.querySelectorAll('button, [role="button"], a'))
                    .map((node) => ({
                        text: text(node),
                        aria: node.getAttribute('aria-label') || '',
                        disabled: Boolean(node.disabled || node.getAttribute('aria-disabled') === 'true')
                    }))
                    .filter((item) => item.text || item.aria)
                    .slice(0, 120);
                const reviewish = Array.from(document.querySelectorAll('[data-testid*="review" i], [aria-label*="review" i], article, section'))
                    .map((node) => text(node))
                    .filter((value) => value && value.length > 20)
                    .slice(0, 40);
                return {
                    url: location.href,
                    title: document.title,
                    body: (document.body?.innerText || '').slice(0, 8000),
                    buttons,
                    reviewish
                };
            }
            """
        )
    except Exception as error:
        data = {"error": str(error)}

    source_place_id = attraction_source_place_id(attraction)
    path = ATTRACTION_REVIEW_DEBUG_DIR / f"{safe_filename(source_place_id)}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"name: {attraction.get('name')}",
        f"attraction_id: {source_place_id}",
        f"url: {getattr(page, 'url', '')}",
        "",
        json.dumps(data, indent=2, ensure_ascii=False),
    ]
    try:
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  Attraction review debug saved: {path}")
    except Exception as error:
        print(f"  Attraction review debug save failed: {error}")


async def scrape_attractions_in_context(
    context: BrowserContext,
    catalog_mode: bool = False,
) -> list[dict[str, Any]]:
    page = await context.new_page()
    all_attractions: dict[str, dict[str, Any]] = {}
    try:
        print()
        print("=" * 60)
        print("COLLECTING BOOKING.COM ATTRACTIONS")
        print("=" * 60)

        destinations = (
            CATALOG_ATTRACTION_DESTINATIONS
            if catalog_mode
            else [{"name": "Configured destination", "dest_id": ATTRACTIONS_DEST_ID}]
        )
        if catalog_mode:
            print(f"Catalog attraction destinations: {len(destinations)}")
            print()

        async def scrape_destination(destination: dict[str, str]) -> None:
            destination_name = destination.get("name") or destination.get("dest_id") or "Unknown"
            dest_id = str(destination.get("dest_id") or ATTRACTIONS_DEST_ID)
            attractions_url = attraction_search_url(dest_id, catalog_mode)

            print("-" * 60)
            print(f"Attraction destination: {destination_name}")
            print("-" * 60)
            print(f"Attractions URL: {attractions_url}")
            if catalog_mode:
                print("Date mode: catalog discovery, no attraction availability date filter")
            else:
                print(f"Start date: {CHECKIN}")
                print(f"End date: {CHECKOUT}")
            print(f"Destination ID: {dest_id}")
            print()

            captured_request = await wait_for_attraction_request(page, attractions_url)
            if captured_request is None:
                print("No attractions API request was captured.")
                return

            original_body = parse_request_body(captured_request)
            if not isinstance(original_body, dict):
                print("Could not parse the captured attractions request body.")
                return

            endpoint_url = captured_request.url
            headers = await build_fetch_headers(captured_request)
            template_body = deepcopy(original_body)
            input_data = template_body.setdefault("variables", {}).setdefault("input", {})
            input_data["ufi"] = int(dest_id)
            if catalog_mode:
                remove_catalog_attraction_date_filters(input_data)
            else:
                input_data["filterByStartDate"] = CHECKIN
                input_data["filterByEndDate"] = CHECKOUT
            input_data["limit"] = ATTRACTIONS_PER_PAGE
            input_data["page"] = 1
            input_data["source"] = "search_results"
            variables = template_body.setdefault("variables", {})
            variables["includeOffersRepresentativePrice"] = not catalog_mode
            variables["includeAvailableDates"] = not catalog_mode

            destination_start_count = len(all_attractions)

            for page_number in range(1, MAX_ATTRACTION_PAGES + 1):
                page_body = deepcopy(template_body)
                page_body["variables"]["input"]["page"] = page_number
                page_body["variables"]["input"]["limit"] = ATTRACTIONS_PER_PAGE

                try:
                    payload = await fetch_graphql_page(
                        page=page,
                        endpoint_url=endpoint_url,
                        headers=headers,
                        body=page_body,
                    )
                except Exception as error:
                    print(f"Attractions page {page_number} failed: {error}")
                    break

                products = extract_products(payload)
                if not products:
                    print(f"Attractions page {page_number}: no products returned.")
                    break

                added = 0
                for product in products:
                    key = attraction_dedupe_key(product)
                    if key and key not in all_attractions:
                        all_attractions[key] = {
                            **product,
                            "catalog_destination_name": destination_name,
                            "catalog_destination_id": dest_id,
                        }
                        added += 1

                print(
                    f"Attractions page {page_number:>3} | "
                    f"received {len(products):>2} | new {added:>2} | "
                    f"total unique {len(all_attractions)}"
                )

                if not has_next_page(payload) or len(products) < ATTRACTIONS_PER_PAGE:
                    break
                await page.wait_for_timeout(1000)

            print(
                f"Finished {destination_name}: "
                f"{len(all_attractions) - destination_start_count} new unique attractions."
            )
            print()

        for destination in destinations:
            await scrape_destination(destination)

        return await enrich_attractions_with_detail_pages(
            context,
            list(all_attractions.values()),
        )
    finally:
        await page.close()


async def scrape_reviews_for_attraction(
    page: Page,
    attraction: dict[str, Any],
    existing_source_review_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    existing_source_review_ids = existing_source_review_ids or set()
    try:
        review_request = await wait_for_attraction_review_request(page, attraction)
    except Exception as error:
        print(f"  Attraction review page could not be opened. Skipping: {error}")
        return []

    if review_request is None:
        print("  No attraction review API request captured.")
        return await scrape_visible_attraction_review_cards(
            page,
            attraction,
            existing_source_review_ids,
        )

    original_body = parse_request_body(review_request)
    if not isinstance(original_body, dict):
        print("  Could not parse attraction review request body.")
        return []

    endpoint_url = review_request.url
    headers = await build_fetch_headers(review_request)
    reviews: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    cutoff_date = review_cutoff_date()
    structured_total: int | None = None

    async def add_visible_reviews() -> int:
        visible_reviews = await scrape_visible_attraction_review_cards(
            page,
            attraction,
            existing_source_review_ids,
        )
        added = 0
        for review in visible_reviews:
            key = attraction_review_content_key(review)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            reviews.append(review)
            added += 1
        return added

    for page_number in review_page_numbers():
        page_body = json.loads(json.dumps(original_body))
        prepare_attraction_review_request_body(page_body, page_number + 1)
        try:
            payload = await fetch_graphql_page(
                page=page,
                endpoint_url=endpoint_url,
                headers=headers,
                body=page_body,
            )
        except Exception as error:
            print(f"  Attraction review page {page_number + 1} failed: {error}")
            break

        if structured_total is None:
            structured_total = attraction_review_total(payload)

        raw_reviews = find_review_items(payload)
        if not raw_reviews:
            print(
                f"  Structured attraction review page {page_number + 1}: "
                "no review records returned."
            )
            if page_number == 0:
                print("  Reading visible attraction reviews from the page.")
                return await scrape_visible_attraction_review_cards(
                    page,
                    attraction,
                    existing_source_review_ids,
                )
            break

        added = 0
        skipped = 0
        for raw_review in raw_reviews:
            review = prepare_attraction_review(
                normalize_review(raw_review, {"hotel_id": attraction_source_place_id(attraction)}),
                attraction,
            )
            source_review_id = stable_review_id(review)
            collect, _should_stop, _reason = should_collect_review(
                review,
                source_review_id,
                existing_source_review_ids,
                None,
                cutoff_date,
            )
            if not collect:
                skipped += 1
                continue
            content_key = attraction_review_content_key(review)
            if content_key not in seen_keys:
                seen_keys.add(content_key)
                reviews.append(review)
                added += 1

        print(
            f"  Structured attraction review page {page_number + 1}: "
            f"received {len(raw_reviews)}, new {added}, skipped {skipped}, "
            f"total {len(reviews)}"
        )
        if page_number > 0 and added == 0:
            print("  No additional attraction reviews found on this page. Stopping collection.")
            break
        if structured_total is not None and len(reviews) >= structured_total:
            print("  Reached the API-reported attraction review total.")
            break
        if len(raw_reviews) < REVIEWS_PER_PAGE:
            break
        await page.wait_for_timeout(800)

    return reviews


async def scrape_reviews_for_attractions(
    context: BrowserContext,
    attractions: list[dict[str, Any]],
    existing_review_ids_by_place_source_id: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    existing_review_ids_by_place_source_id = existing_review_ids_by_place_source_id or {}
    reviewable_attractions = [
        attraction
        for attraction in attractions
        if attraction.get("property_url")
    ]
    all_reviews: list[dict[str, Any]] = []
    page = await context.new_page()
    try:
        print()
        print("=" * 60)
        print("COLLECTING ATTRACTION REVIEWS")
        print("=" * 60)
        print(f"Attractions with URLs: {len(reviewable_attractions)}")
        for index, attraction in enumerate(reviewable_attractions, start=1):
            print(
                f"[{index}/{len(reviewable_attractions)}] "
                f"{attraction.get('name') or attraction.get('attraction_id')}"
            )
            source_place_id = attraction_source_place_id(attraction)
            place_source_id = attraction_place_source_id(source_place_id)
            try:
                reviews = await scrape_reviews_for_attraction(
                    page,
                    attraction,
                    existing_review_ids_by_place_source_id.get(place_source_id, set()),
                )
            except Exception as error:
                print(f"  Attraction review collection failed. Skipping: {error}")
                reviews = []
            all_reviews.extend(reviews)
            await page.wait_for_timeout(1000)
    finally:
        await page.close()
    return all_reviews
