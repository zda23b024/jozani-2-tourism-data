import asyncio
import json
from copy import deepcopy
from typing import Any
from urllib.parse import quote_plus

from playwright.async_api import BrowserContext, Page, Request

from config.configuration import (
    ATTRACTIONS_DEST_ID,
    ATTRACTIONS_PER_PAGE,
    ATTRACTIONS_URL,
    CHECKIN,
    CHECKOUT,
    MAX_ATTRACTION_PAGES,
)
from utils.browser_helpers import (
    accept_cookies,
    build_fetch_headers,
    fetch_graphql_page,
    parse_request_body,
)
from utils.helpers import first_nonempty, join_values, nested_get


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


async def wait_for_attraction_request(page: Page) -> Request | None:
    captured_request = None
    request_found = asyncio.Event()

    async def request_handler(request: Request) -> None:
        nonlocal captured_request
        if captured_request is None and is_attraction_search_request(request):
            captured_request = request
            request_found.set()
            print("Captured the browser-generated attractions API request.")

    page.on("request", request_handler)
    await page.goto(ATTRACTIONS_URL, wait_until="domcontentloaded", timeout=120_000)
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
        await asyncio.wait_for(request_found.wait(), timeout=90)
    except asyncio.TimeoutError:
        pass
    finally:
        try:
            page.remove_listener("request", request_handler)
        except Exception:
            pass

    return captured_request


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
    )
    if not isinstance(price, dict):
        return {"price": None, "currency": None}
    return {
        "price": first_nonempty(
            price.get("chargeAmount"),
            price.get("publicAmount"),
        ),
        "currency": price.get("currency"),
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
        "property_url": (
            "https://www.booking.com/attractions/"
            f"{quote_plus(str(product.get('slug') or product.get('id') or ''))}.html"
        ),
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


async def scrape_attractions_in_context(
    context: BrowserContext,
) -> list[dict[str, Any]]:
    page = await context.new_page()
    try:
        print()
        print("=" * 60)
        print("COLLECTING BOOKING.COM ATTRACTIONS")
        print("=" * 60)
        print(f"Attractions URL: {ATTRACTIONS_URL}")
        print(f"Start date: {CHECKIN}")
        print(f"End date: {CHECKOUT}")
        print(f"Destination ID: {ATTRACTIONS_DEST_ID}")
        print()

        captured_request = await wait_for_attraction_request(page)
        if captured_request is None:
            print("No attractions API request was captured.")
            return []

        original_body = parse_request_body(captured_request)
        if not isinstance(original_body, dict):
            print("Could not parse the captured attractions request body.")
            return []

        endpoint_url = captured_request.url
        headers = await build_fetch_headers(captured_request)
        template_body = deepcopy(original_body)
        input_data = template_body.setdefault("variables", {}).setdefault("input", {})
        input_data["ufi"] = int(ATTRACTIONS_DEST_ID)
        input_data["filterByStartDate"] = CHECKIN
        input_data["filterByEndDate"] = CHECKOUT
        input_data["limit"] = ATTRACTIONS_PER_PAGE
        input_data["page"] = 1
        input_data["source"] = "search_results"
        template_body.setdefault("variables", {})["includeOffersRepresentativePrice"] = True
        template_body.setdefault("variables", {})["includeAvailableDates"] = True

        all_attractions: dict[str, dict[str, Any]] = {}

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
                key = str(product.get("attraction_id") or product.get("name") or "")
                if key and key not in all_attractions:
                    all_attractions[key] = product
                    added += 1

            print(
                f"Attractions page {page_number:>3} | "
                f"received {len(products):>2} | new {added:>2} | "
                f"total unique {len(all_attractions)}"
            )

            if not has_next_page(payload) or len(products) < ATTRACTIONS_PER_PAGE:
                break
            await page.wait_for_timeout(1000)

        return list(all_attractions.values())
    finally:
        await page.close()
