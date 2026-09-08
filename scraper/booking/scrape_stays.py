import asyncio
import itertools
import re
from copy import deepcopy
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

from playwright.async_api import BrowserContext, Page, Request

from config.configuration import (
    ADULTS,
    CATALOG_SEARCH_TERMS,
    CHECKIN,
    CHECKOUT,
    CHILDREN,
    MAX_CATALOG_HOTEL_PAGES,
    MAX_HOTEL_PAGES,
    ROOMS,
    ROWS_PER_PAGE,
    SEARCH_API_CAPTURE_TIMEOUT_SECONDS,
    SEARCH_TERM,
    SEARCH_URL,
    STAYS_AID,
    STAYS_DEST_ID,
    STAYS_DEST_TYPE,
    STAYS_LANGUAGE,
    STAYS_SEARCH_TERM,
)
from utils.browser_helpers import (
    accept_cookies,
    build_fetch_headers,
    close_context,
    fetch_graphql_page,
    launch_context,
    parse_request_body,
)
from utils.console_output import print_catalog_complete, print_category_header
from utils.helpers import (
    find_property_url,
    first_nonempty,
    join_values,
    nested_get,
    normalize_image_url,
    safe_filename,
    translation_text,
)


def hotel_dedupe_key(hotel: dict[str, Any]) -> str:
    hotel_id = hotel.get("hotel_id")
    if hotel_id is not None:
        return f"id:{hotel_id}"
    return (
        f"name:{hotel.get('name')}|"
        f"lat:{hotel.get('latitude')}|"
        f"lon:{hotel.get('longitude')}"
    )


def stays_search_url(search_term: str, catalog_mode: bool) -> str:
    if catalog_mode:
        if search_term == STAYS_SEARCH_TERM:
            return (
                f"https://www.booking.com/searchresults.{STAYS_LANGUAGE}.html"
                f"?ss={quote_plus(search_term)}"
                f"&ssne={quote_plus(search_term)}"
                f"&ssne_untouched={quote_plus(search_term)}"
                f"&aid={STAYS_AID}"
                f"&lang={STAYS_LANGUAGE}"
                f"&dest_id={STAYS_DEST_ID}"
                f"&dest_type={quote_plus(STAYS_DEST_TYPE)}"
                f"&group_adults={ADULTS}"
                f"&no_rooms={ROOMS}"
                f"&group_children={CHILDREN}"
                "&order=class"
            )
        return (
            "https://www.booking.com/searchresults.en-gb.html"
            f"?ss={quote_plus(search_term)}"
            f"&ssne={quote_plus(search_term)}"
            f"&ssne_untouched={quote_plus(search_term)}"
            "&order=class"
        )
    return SEARCH_URL


def raw_query_for_session(search_term: str, catalog_mode: bool) -> str:
    if catalog_mode:
        if search_term == STAYS_SEARCH_TERM:
            return (
                f"/searchresults.{STAYS_LANGUAGE}.html"
                f"?aid={STAYS_AID}"
                f"&ss={quote_plus(search_term)}"
                f"&ssne={quote_plus(search_term)}"
                f"&ssne_untouched={quote_plus(search_term)}"
                f"&lang={STAYS_LANGUAGE}"
                f"&dest_id={STAYS_DEST_ID}"
                f"&dest_type={quote_plus(STAYS_DEST_TYPE)}"
                f"&group_adults={ADULTS}"
                f"&no_rooms={ROOMS}"
                f"&group_children={CHILDREN}"
            )
        return (
            "/searchresults.en-gb.html"
            f"?ss={quote_plus(search_term)}"
            f"&ssne={quote_plus(search_term)}"
            f"&ssne_untouched={quote_plus(search_term)}"
            "&order=class"
        )
    return (
        f"/searchresults.{STAYS_LANGUAGE}.html"
        f"?ss={quote_plus(search_term)}"
        f"&ssne={quote_plus(search_term)}"
        f"&ssne_untouched={quote_plus(search_term)}"
        f"&aid={STAYS_AID}"
        f"&lang={STAYS_LANGUAGE}"
        f"&dest_id={STAYS_DEST_ID}"
        f"&dest_type={quote_plus(STAYS_DEST_TYPE)}"
        f"&checkin={CHECKIN}"
        f"&checkout={CHECKOUT}"
        f"&group_adults={ADULTS}"
        f"&no_rooms={ROOMS}"
        f"&group_children={CHILDREN}"
    )


def extract_photo_url(item: dict[str, Any]) -> str | None:
    basic = item.get("basicPropertyData") or {}
    main_photo = (basic.get("photos") or {}).get("main") or {}
    possible_urls = [
        nested_get(main_photo, "highResJpegUrl", "relativeUrl"),
        nested_get(main_photo, "highResUrl", "relativeUrl"),
        nested_get(main_photo, "lowResJpegUrl", "relativeUrl"),
        nested_get(main_photo, "lowResUrl", "relativeUrl"),
    ]
    for photo in item.get("topPhotos") or []:
        if isinstance(photo, dict):
            possible_urls.extend(
                [
                    nested_get(photo, "highResJpegUrl", "relativeUrl"),
                    nested_get(photo, "highResUrl", "relativeUrl"),
                    nested_get(photo, "lowResJpegUrl", "relativeUrl"),
                    nested_get(photo, "lowResUrl", "relativeUrl"),
                ]
            )
    for url in possible_urls:
        normalized = normalize_image_url(url)
        if normalized:
            return normalized
    return None


def extract_badges(item: dict[str, Any]) -> str | None:
    values = []
    for badge in item.get("propertyUspBadges") or []:
        if isinstance(badge, dict):
            values.append(
                first_nonempty(badge.get("translatedName"), badge.get("name"))
            )
    for badge in item.get("badges") or []:
        if isinstance(badge, dict):
            values.append(translation_text(badge.get("caption")))
    return join_values(values)


def extract_sustainability(item: dict[str, Any]) -> tuple[Any, str | None]:
    sustainability = item.get("propertySustainability") or {}
    certifications = [
        certification.get("name")
        for certification in sustainability.get("certifications") or []
        if isinstance(certification, dict)
    ]
    return sustainability.get("isSustainable"), join_values(certifications)


def extract_price(item: dict[str, Any]) -> dict[str, Any]:
    price_info = item.get("priceDisplayInfoIrene") or {}
    amount_per_stay = (
        (price_info.get("displayPrice") or {}).get("amountPerStay") or {}
    )
    return {
        "price": amount_per_stay.get("amount"),
        "currency": amount_per_stay.get("currency"),
    }


def strip_availability_query_params(url: str) -> str:
    blocked_params = {
        "checkin",
        "checkout",
        "group_adults",
        "group_children",
        "no_rooms",
        "req_adults",
        "req_children",
        "req_rooms",
        "selected_currency",
    }
    parts = urlsplit(url)
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in blocked_params
        ],
        doseq=True,
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def property_url_from_item(
    item: dict[str, Any],
    page_name: Any,
    country_code: Any,
    include_search_dates: bool = True,
) -> str | None:
    property_url = find_property_url(item)
    if not property_url and page_name:
        page_path = str(page_name).strip("/")
        if "/" in page_path:
            property_url = f"https://www.booking.com/hotel/{page_path}.en-gb.html"
        elif country_code:
            property_url = (
                "https://www.booking.com/hotel/"
                f"{str(country_code).lower()}/{page_path}.en-gb.html"
            )
        else:
            property_url = f"https://www.booking.com/hotel/{page_path}.en-gb.html"
    if not property_url:
        return None
    if not include_search_dates:
        return strip_availability_query_params(property_url)
    separator = "&" if "?" in property_url else "?"
    return (
        f"{property_url}{separator}checkin={CHECKIN}"
        f"&checkout={CHECKOUT}"
        f"&group_adults={ADULTS}"
        f"&no_rooms={ROOMS}"
        f"&group_children={CHILDREN}"
    )


def extract_hotel(
    item: dict[str, Any],
    include_search_dates: bool = True,
) -> dict[str, Any]:
    basic = item.get("basicPropertyData") or {}
    basic_location = basic.get("location") or {}
    displayed_location = item.get("location") or {}
    reviews = basic.get("reviewScore") or {}
    star_rating = basic.get("starRating") or {}
    display_name = item.get("displayName") or {}
    policies = item.get("policies") or {}
    meal_plan = item.get("mealPlanIncluded") or {}
    sold_out = item.get("soldOutInfo") or {}
    page_name = basic.get("pageName")
    country_code = basic_location.get("countryCode")
    sustainable, certifications = extract_sustainability(item)

    return {
        "source": "booking",
        "hotel_id": basic.get("id"),
        "name": first_nonempty(
            display_name.get("text"),
            item.get("generatedPropertyTitle"),
        ),
        "accommodation_type_id": basic.get("accommodationTypeId"),
        "property_url": property_url_from_item(
            item,
            page_name,
            country_code,
            include_search_dates=include_search_dates,
        ),
        "page_name": page_name,
        "address": basic_location.get("address"),
        "city": basic_location.get("city"),
        "country_code": country_code,
        "latitude": basic_location.get("latitude"),
        "longitude": basic_location.get("longitude"),
        "display_location": displayed_location.get("displayLocation"),
        "distance_from_center": displayed_location.get("mainDistance"),
        "distance_meters": displayed_location.get("geoDistanceMeters"),
        "beach_distance": displayed_location.get("beachDistance"),
        "beach_walking_time": displayed_location.get("beachWalkingTime"),
        "nearby_beaches": join_values(
            displayed_location.get("nearbyBeachNames") or []
        ),
        "centrally_located": displayed_location.get("isCentrallyLocated"),
        "review_score": reviews.get("score"),
        "review_count": reviews.get("reviewCount"),
        "review_score_text": translation_text(reviews.get("totalScoreTextTag")),
        "star_rating": star_rating.get("value"),
        "description": nested_get(item, "description", "text"),
        "description_summary": item.get("descriptionSummary"),
        "photo_url": extract_photo_url(item),
        "property_badges": extract_badges(item),
        "meal_plan": meal_plan.get("text"),
        "meal_plan_type": meal_plan.get("mealPlanType"),
        "free_cancellation": policies.get("showFreeCancellation"),
        "no_prepayment": policies.get("showNoPrepayment"),
        "pets_free": policies.get("showPetsAllowedForFree"),
        "sustainable": sustainable,
        "sustainability_certifications": certifications,
        "property_usp_facilities": join_values(
            [
                badge.get("translatedName") or badge.get("name")
                for badge in item.get("propertyUspBadges") or []
                if isinstance(badge, dict)
            ]
        ),
        "sold_out": sold_out.get("isSoldOut"),
        **extract_price(item),
    }


def extract_results(
    payload: dict[str, Any],
    include_search_dates: bool = True,
) -> list[dict[str, Any]]:
    results = nested_get(payload, "data", "searchQueries", "search", "results")
    if not isinstance(results, list):
        return []
    return [
        extract_hotel(item, include_search_dates=include_search_dates)
        for item in results
        if isinstance(item, dict)
    ]


def extract_total_results(payload: dict[str, Any]) -> int | None:
    value = nested_get(
        payload,
        "data",
        "searchQueries",
        "search",
        "pagination",
        "nbResultsTotal",
    )
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def remove_catalog_availability_filters(value: Any) -> None:
    availability_keys = {
        "checkin",
        "checkout",
        "checkindate",
        "checkoutdate",
        "checkin_date",
        "checkout_date",
        "startdate",
        "enddate",
        "start_date",
        "end_date",
        "arrivaldate",
        "departuredate",
        "arrival_date",
        "departure_date",
        "adults",
        "children",
        "rooms",
        "group_adults",
        "group_children",
        "no_rooms",
        "nbadults",
        "nbchildren",
        "nbrooms",
        "numberofadults",
        "numberofchildren",
        "numberofrooms",
    }
    if isinstance(value, dict):
        for key in list(value.keys()):
            if str(key).lower() in availability_keys:
                value.pop(key, None)
                continue
            remove_catalog_availability_filters(value[key])
    elif isinstance(value, list):
        for child in value:
            remove_catalog_availability_filters(child)


def is_search_graphql_request(request: Request) -> bool:
    if "/dml/graphql" not in request.url or request.method != "POST":
        return False
    body = parse_request_body(request)
    if not body:
        return False
    operation_name = str(body.get("operationName") or "").lower()
    query = str(body.get("query") or "").lower()
    input_data = (body.get("variables") or {}).get("input") or {}
    return any(
        value in operation_name
        for value in ["fullsearch", "searchresults", "searchproperties"]
    ) or (
        isinstance(input_data.get("pagination"), dict)
        and "search" in query
        and "results" in query
    )


async def wait_for_initial_request(
    page: Page,
    search_url: str,
) -> Request | None:
    captured_request = None
    request_found = asyncio.Event()

    async def request_handler(request: Request) -> None:
        nonlocal captured_request
        if captured_request is None and is_search_graphql_request(request):
            captured_request = request
            request_found.set()
            print("Captured the browser-generated search API request.")

    page.on("request", request_handler)
    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=120_000)
        await accept_cookies(page)

        print()
        print("A browser window has opened.")
        print("Complete any normal verification shown by Booking.com.")
        print("Wait until the search results appear.")
        print()

        for attempt in range(3):
            if request_found.is_set():
                break
            try:
                await page.wait_for_timeout(5000)
                await page.evaluate(
                    'window.scrollTo({top: document.body.scrollHeight, behavior: "smooth"})'
                )
                await page.wait_for_timeout(3000)
                button = page.locator(
                    '[data-testid="searchbox-submit-button"], '
                    'button[type="submit"]:has-text("Search"), '
                    'button:has-text("Search")'
                ).first
                if await button.is_visible(timeout=1500):
                    print("Clicking Search to trigger the API request.")
                    await button.click()
                    await page.wait_for_timeout(5000)
                if request_found.is_set():
                    break
                print(
                    f"Still waiting for a search API request after browser nudge {attempt + 1}/3..."
                )
            except Exception:
                continue

        try:
            print(
                "Final wait for search API request: "
                f"{SEARCH_API_CAPTURE_TIMEOUT_SECONDS} seconds..."
            )
            await asyncio.wait_for(
                request_found.wait(),
                timeout=SEARCH_API_CAPTURE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            pass
        return captured_request
    finally:
        try:
            page.remove_listener("request", request_handler)
        except Exception:
            pass


def clean_text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def extract_time_from_text(text: str, label: str) -> str | None:
    pattern = rf"{re.escape(label)}\s*(?:from|until|:)?\s*([0-2]?\d:[0-5]\d(?:\s*[-–]\s*[0-2]?\d:[0-5]\d)?)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return clean_text(match.group(1)) if match else None


async def scrape_hotel_detail_page(
    page: Page,
    hotel: dict[str, Any],
) -> dict[str, Any]:
    url = hotel.get("property_url")
    if not url:
        return {}

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        await accept_cookies(page)
        await page.wait_for_timeout(2500)
        await page.evaluate(
            'window.scrollTo({top: Math.min(document.body.scrollHeight, 4000), behavior: "smooth"})'
        )
        await page.wait_for_timeout(1500)
    except Exception as error:
        print(f"  Detail page failed for {hotel.get('name')}: {error}")
        return {}

    try:
        data = await page.evaluate(
            """
            () => {
                const text = (el) => (el?.innerText || el?.textContent || '').trim();
                const unique = (items) => [...new Set(items.map(v => (v || '').trim()).filter(Boolean))];
                const facilitySelectors = [
                    '[data-testid*="facility"]',
                    '[data-testid="property-most-popular-facilities-wrapper"] li',
                    '[data-testid="property-section--content"] li',
                    '.hp_desc_important_facilities li',
                    '.important_facility',
                    '.facility-badge',
                    '.bui-list__item'
                ];
                const policySelectors = [
                    '[data-testid*="policy"]',
                    '[data-testid*="house-rules"]',
                    '#hotelPoliciesInc',
                    '.hotelPolicies',
                    '.hp-policy-section',
                    '.description--house-rules'
                ];
                const images = unique(
                    [...document.images]
                        .map(img => img.currentSrc || img.src || img.getAttribute('data-src'))
                        .filter(src => src && /^https?:/.test(src))
                );
                const facilities = unique(
                    facilitySelectors.flatMap(selector =>
                        [...document.querySelectorAll(selector)].map(text)
                    )
                ).filter(value => value.length <= 120);
                const policies = unique(
                    policySelectors.flatMap(selector =>
                        [...document.querySelectorAll(selector)].map(text)
                    )
                ).filter(value => value.length <= 2000);
                const bodyText = document.body.innerText || '';
                return {images, facilities, policies, bodyText};
            }
            """
        )
    except Exception:
        return {}

    body_text = clean_text(data.get("bodyText") if isinstance(data, dict) else "")
    facilities = data.get("facilities") if isinstance(data, dict) else []
    policies = data.get("policies") if isinstance(data, dict) else []
    images = data.get("images") if isinstance(data, dict) else []

    detail = {
        "full_facilities": join_values(facilities or []),
        "gallery_photo_urls": images or [],
        "house_rules_text": join_values(policies or [], "\n\n"),
        "checkin_time": extract_time_from_text(body_text or "", "Check-in"),
        "checkout_time": extract_time_from_text(body_text or "", "Check-out"),
        "child_policy": None,
        "pet_policy": None,
        "payment_policy": None,
    }

    if body_text:
        child_match = re.search(r"(Children[^.]{0,500})", body_text, re.IGNORECASE)
        pet_match = re.search(r"(Pets[^.]{0,500})", body_text, re.IGNORECASE)
        payment_match = re.search(r"(Payment[^.]{0,500}|Cards accepted[^.]{0,500})", body_text, re.IGNORECASE)
        detail["child_policy"] = clean_text(child_match.group(1)) if child_match else None
        detail["pet_policy"] = clean_text(pet_match.group(1)) if pet_match else None
        detail["payment_policy"] = clean_text(payment_match.group(1)) if payment_match else None

    return {key: value for key, value in detail.items() if value not in (None, "", [], {})}


async def enrich_hotels_with_detail_pages(
    context: BrowserContext,
    hotels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not hotels:
        return hotels

    print()
    print("=" * 60)
    print("ENRICHING HOTEL DETAIL PAGES")
    print("=" * 60)
    detail_page = await context.new_page()
    try:
        enriched = []
        for index, hotel in enumerate(hotels, start=1):
            print(f"[{index}/{len(hotels)}] Detail: {hotel.get('name') or hotel.get('hotel_id')}")
            details = await scrape_hotel_detail_page(detail_page, hotel)
            enriched.append({**hotel, **details})
            await detail_page.wait_for_timeout(800)
        return enriched
    finally:
        await detail_page.close()


def hotel_pagination_stop_reason(
    reported_total: int | None,
    offset: int,
    received: int,
    added: int,
    repeated_pages: int,
    no_progress_pages: int,
) -> str | None:
    if received == 0:
        return "empty"
    if reported_total is not None and offset + received >= reported_total:
        return "reported_total"
    if repeated_pages >= 3 or no_progress_pages >= 3:
        return "no_progress"
    return None


async def scrape_hotels_in_context(
    context: BrowserContext,
    catalog_mode: bool = False,
) -> list[dict[str, Any]]:
    page = context.pages[0] if context.pages else await context.new_page()
    max_pages = MAX_CATALOG_HOTEL_PAGES if catalog_mode else MAX_HOTEL_PAGES
    all_hotels: dict[str, dict[str, Any]] = {}

    async def scrape_search_term(search_term: str) -> None:
        search_url = stays_search_url(search_term, catalog_mode)
        print(f"Search location: {search_term}")
        if catalog_mode:
            print("Date mode: catalog discovery, no availability date filter")
        else:
            print(f"Check-in date: {CHECKIN}")
            print(f"Check-out date: {CHECKOUT}")
            print("Date mode: automatic current-day scrape")
        print(f"Search URL: {search_url}")
        print()

        captured_request = await wait_for_initial_request(page, search_url)
        if captured_request is None:
            print("No search API request was captured.")
            return

        original_body = parse_request_body(captured_request)
        if not isinstance(original_body, dict):
            print("Could not parse the captured request body.")
            return

        endpoint_url = captured_request.url
        headers = await build_fetch_headers(captured_request)
        template_body = deepcopy(original_body)
        input_data = template_body.setdefault("variables", {}).setdefault("input", {})
        input_data["doAvailabilityCheck"] = not catalog_mode
        location = input_data.setdefault("location", {})
        location["searchString"] = search_term
        if catalog_mode and search_term == STAYS_SEARCH_TERM:
            location["destType"] = STAYS_DEST_TYPE.upper()
            location["destId"] = STAYS_DEST_ID
        input_data["filters"] = {}
        if catalog_mode:
            remove_catalog_availability_filters(input_data)
        input_data.setdefault("pagination", {})["rowsPerPage"] = ROWS_PER_PAGE
        input_data["pagination"]["offset"] = 0
        input_data["rawQueryForSession"] = raw_query_for_session(
            search_term,
            catalog_mode,
        )

        reported_total = None
        term_start_count = len(all_hotels)
        previous_page_ids: tuple[str, ...] | None = None
        repeated_pages = 0
        no_progress_pages = 0
        print("Starting API pagination...")
        print()

        page_numbers = itertools.count() if max_pages is None else range(max_pages)
        for page_number in page_numbers:
            offset = page_number * ROWS_PER_PAGE
            page_body = deepcopy(template_body)
            page_input = page_body["variables"]["input"]
            page_input["pagination"]["offset"] = offset
            page_input["pagination"]["rowsPerPage"] = ROWS_PER_PAGE
            page_input["clientSideRequestId"] = f"playwright-{safe_filename(search_term)}-{page_number}-{offset}"

            try:
                payload = await fetch_graphql_page(
                    page=page,
                    endpoint_url=endpoint_url,
                    headers=headers,
                    body=page_body,
                )
            except Exception as error:
                print(f"Page {page_number + 1} failed: {error}")
                break

            if reported_total is None:
                reported_total = extract_total_results(payload)
                if reported_total is not None:
                    print("API-reported total results:", reported_total)

            page_hotels = extract_results(
                payload,
                include_search_dates=not catalog_mode,
            )
            if not page_hotels:
                print(f"Offset {offset}: no results returned. Pagination finished.")
                break

            added = 0
            for hotel in page_hotels:
                key = hotel_dedupe_key(hotel)
                if key not in all_hotels:
                    all_hotels[key] = {
                        **hotel,
                        "catalog_search_term": search_term,
                    }
                    added += 1

            print(
                f"Page {page_number + 1:>3} | offset {offset:>5} | "
                f"received {len(page_hotels):>2} | new {added:>2} | "
                f"total unique {len(all_hotels)}"
            )

            page_ids = tuple(sorted(hotel_dedupe_key(hotel) for hotel in page_hotels))
            if page_ids == previous_page_ids:
                repeated_pages += 1
            else:
                repeated_pages = 0
            previous_page_ids = page_ids
            if added == 0:
                no_progress_pages += 1
            else:
                no_progress_pages = 0

            stop_reason = hotel_pagination_stop_reason(
                reported_total,
                offset,
                len(page_hotels),
                added,
                repeated_pages,
                no_progress_pages,
            )
            if stop_reason == "reported_total":
                print("Reached the API-reported total.")
                break
            if stop_reason == "no_progress":
                print("WARN Pagination made no progress for three consecutive pages; stopping.")
                break
            if len(page_hotels) < ROWS_PER_PAGE:
                print(
                    "WARN Short page; API reports more results, continuing."
                    if reported_total is not None
                    else "WARN Short page; continuing until the API returns no results."
                )
            await page.wait_for_timeout(1200)

        print(
            f"Finished {search_term}: "
            f"{len(all_hotels) - term_start_count} new unique properties."
        )
        print()

    search_terms = CATALOG_SEARCH_TERMS if catalog_mode else [SEARCH_TERM]
    if catalog_mode:
        print_category_header("Booking.com", "Hotels")
        print(f"Catalog search terms: {len(search_terms)}")
        print()

    for index, search_term in enumerate(search_terms, start=1):
        if catalog_mode:
            print("-" * 60)
            print(f"Catalog area {index}/{len(search_terms)}")
            print("-" * 60)
        await scrape_search_term(search_term)

    print_catalog_complete("Hotels", len(all_hotels))

    return await enrich_hotels_with_detail_pages(
        context,
        list(all_hotels.values()),
    )
