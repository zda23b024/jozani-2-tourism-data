import html
import asyncio
import itertools
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

from playwright.async_api import BrowserContext, Page

from config.configuration import (
    ADULTS,
    CHECKIN,
    CHECKOUT,
    CHILDREN,
    MAX_TRIPADVISOR_HOTEL_PAGES,
    ROOMS,
    TRIPADVISOR_CATALOG_TEST_FIRST_PAGE_ONLY,
    TRIPADVISOR_GEO_ID,
    TRIPADVISOR_HOTEL_GRAPHQL_ENABLED,
    TRIPADVISOR_HOTEL_GRAPHQL_QUERY_ID,
    TRIPADVISOR_HOTEL_GRAPHQL_URL,
    TRIPADVISOR_HOTEL_PRICING_MODE,
    TRIPADVISOR_HOTEL_SORT,
    TRIPADVISOR_RESULTS_PER_PAGE,
    TRIPADVISOR_SEARCH_URL,
)
from utils.browser_helpers import accept_cookies, collect_page_debug
from utils.console_output import (
    print_catalog_complete,
    print_catalog_page,
    print_category_header,
)
from utils.helpers import first_nonempty, join_values, safe_filename


TRIPADVISOR_SOURCE_ID = "tripadvisor"
TRIPADVISOR_GRAPHQL_MAX_RETRIES = 3


@dataclass
class TripadvisorGraphQLResult:
    cards: list[dict[str, Any]]
    raw_count: int
    metadata: dict[str, Any]
    blocked: bool = False
    failed: bool = False


@dataclass
class TripadvisorHotelPageStat:
    offset: int
    raw_count: int
    new_unique: int
    total_unique: int
    metadata: dict[str, Any]


def tripadvisor_hotel_page_numbers() -> range | itertools.count:
    if TRIPADVISOR_CATALOG_TEST_FIRST_PAGE_ONLY:
        return range(1, 2)
    if MAX_TRIPADVISOR_HOTEL_PAGES is None:
        return itertools.count(1)
    return range(1, MAX_TRIPADVISOR_HOTEL_PAGES + 1)


async def tripadvisor_cookie_value(context: BrowserContext, name: str) -> str | None:
    try:
        cookies = await context.cookies("https://www.tripadvisor.com")
    except Exception:
        return None
    for cookie in cookies:
        if cookie.get("name") == name and cookie.get("value"):
            return str(cookie["value"])
    return None


async def tripadvisor_hotel_graphql_payload(
    page: Page,
    page_number: int,
) -> list[dict[str, Any]]:
    offset = (page_number - 1) * TRIPADVISOR_RESULTS_PER_PAGE
    session_id = (
        await tripadvisor_cookie_value(page.context, "TASID")
        or await tripadvisor_cookie_value(page.context, "TASession")
        or uuid4().hex.upper()
    )
    pageview_id = str(uuid4())
    return [
        {
            "variables": {
                "geoId": int(TRIPADVISOR_GEO_ID),
                "blenderId": None,
                "boundingBox": None,
                "centerAndRadius": None,
                "travelInfo": {
                    "usedDefaultDates": False,
                    "checkInDate": CHECKIN,
                    "checkOutDate": CHECKOUT,
                    "rooms": ROOMS,
                    "adults": ADULTS,
                    "childrenAges": [] if CHILDREN == 0 else [12] * CHILDREN,
                },
                "currency": "USD",
                "pricingMode": TRIPADVISOR_HOTEL_PRICING_MODE,
                "filters": {
                    "selectTravelersChoiceWinner": False,
                    "selectTravelersChoiceBOTBWinner": False,
                    "minRating": None,
                    "neighborhoodsOrNear": None,
                    "priceRange": None,
                    "amenities": None,
                    "brands": None,
                    "classes": None,
                    "styles": None,
                    "hoteltypes": None,
                    "categories": None,
                    "anyTags": None,
                    "hotelowners": None,
                },
                "offset": offset,
                "limit": TRIPADVISOR_RESULTS_PER_PAGE,
                "sort": TRIPADVISOR_HOTEL_SORT,
                "clientType": "DESKTOP",
                "loadMapSpecificData": True,
                "viewType": "LIST",
                "productId": "Hotels",
                "pageviewId": pageview_id,
                "sessionId": session_id,
                "route": {
                    "page": "HotelsFusion",
                    "params": {
                        "geoId": int(TRIPADVISOR_GEO_ID),
                        "filters": [{"value": ["true"], "id": "ufe"}],
                        "contentType": "hotel",
                        "webVariant": "HotelsFusion",
                    },
                },
                "userEngagedFilters": True,
                "loadPoiThumbnail": False,
                "loadLocationSEOData": True,
                "loadLocationInfoData": False,
                "loadNearbyPointOfInterestPlaceType": True,
                "metaMarketingQueryString": "",
                "loadReviewSubratingAvgs": False,
                "isSplitMapView": False,
                "polling": False,
                "tertiaryOffers": False,
                "includePhotoSizes": False,
                "requestNumber": page_number - 1,
            },
            "extensions": {
                "preRegisteredQueryId": TRIPADVISOR_HOTEL_GRAPHQL_QUERY_ID,
            },
        }
    ]


def nested_value(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def graphql_response_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def tripadvisor_hotel_results(payload: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in graphql_response_items(payload):
        list_results = nested_value(item, "data", "list", "results")
        if isinstance(list_results, list):
            results.extend(node for node in list_results if isinstance(node, dict))
    return results


def tripadvisor_hotel_metadata(payload: Any) -> dict[str, Any]:
    for item in graphql_response_items(payload):
        metadata = nested_value(item, "data", "list", "searchMetadata")
        if isinstance(metadata, dict):
            return metadata
    return {}


def tripadvisor_hotel_metadata_totals(metadata: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    keys = [
        "totalLocationsInSearch",
        "totalLocationsInScope",
        "totalLocationsFullMatch",
        "countsAccurate",
    ]
    return {
        key: metadata.get(key)
        for key in keys
        if metadata.get(key) not in (None, "")
    }


def format_tripadvisor_hotel_metadata(metadata: dict[str, Any]) -> str:
    totals = tripadvisor_hotel_metadata_totals(metadata)
    if not totals:
        return ""
    labels = {
        "totalLocationsInSearch": "search",
        "totalLocationsInScope": "scope",
        "totalLocationsFullMatch": "full",
        "countsAccurate": "accurate",
    }
    return " | " + " | ".join(
        f"{labels.get(key, key)} {value}" for key, value in totals.items()
    )


def tripadvisor_hotel_page_fingerprint(cards: list[dict[str, Any]]) -> tuple[str, ...]:
    fingerprint: list[str] = []
    for card in cards:
        location_id = valid_tripadvisor_location_id(
            card.get("location_id")
        ) or tripadvisor_location_id_from_node(card)
        url = normalize_tripadvisor_url(card.get("url"))
        fingerprint.append(str(location_id or url or "").strip())
    return tuple(item for item in fingerprint if item)


def print_tripadvisor_hotel_catalog_summary(
    page_stats: list[TripadvisorHotelPageStat],
    stop_reason: str,
) -> None:
    print("[TRIPADVISOR][HOTELS] Catalogue pagination summary")
    print(f"[TRIPADVISOR][HOTELS] Offsets fetched: {len(page_stats)}")
    print(
        "[TRIPADVISOR][HOTELS] Total raw records: "
        f"{sum(stat.raw_count for stat in page_stats)}"
    )
    print(
        "[TRIPADVISOR][HOTELS] Total unique locationIds: "
        f"{page_stats[-1].total_unique if page_stats else 0}"
    )
    print(f"[TRIPADVISOR][HOTELS] Stop reason: {stop_reason}")
    print("[TRIPADVISOR][HOTELS] Last 10 pages:")
    for stat in page_stats[-10:]:
        print_catalog_page(
            page_number=(stat.offset // TRIPADVISOR_RESULTS_PER_PAGE) + 1,
            offset=stat.offset,
            received=stat.raw_count,
            new=stat.new_unique,
            total_unique=stat.total_unique,
            suffix=format_tripadvisor_hotel_metadata(stat.metadata),
        )


def tripadvisor_location_id_from_node(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in {"locationid", "location_id"}:
                location_id = clean_text(child)
                if location_id:
                    return location_id
        for child in value.values():
            location_id = tripadvisor_location_id_from_node(child)
            if location_id:
                return location_id
    elif isinstance(value, list):
        for child in value:
            location_id = tripadvisor_location_id_from_node(child)
            if location_id:
                return location_id
    return None


def tripadvisor_metadata_complete(metadata: dict[str, Any], offset: int, raw_count: int) -> bool:
    total = first_nonempty(
        metadata.get("totalResults"),
        metadata.get("total_results"),
        metadata.get("totalHits"),
        metadata.get("total_hits"),
        metadata.get("totalCount"),
    )
    try:
        total_int = int(str(total).replace(",", ""))
    except (TypeError, ValueError):
        return False
    return offset + raw_count >= total_int


async def fetch_tripadvisor_hotel_graphql_result(
    page: Page,
    page_number: int,
) -> TripadvisorGraphQLResult:
    if not TRIPADVISOR_HOTEL_GRAPHQL_ENABLED:
        return TripadvisorGraphQLResult([], 0, {}, failed=True)
    payload = await tripadvisor_hotel_graphql_payload(page, page_number)
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "origin": "https://www.tripadvisor.com",
        "referer": TRIPADVISOR_SEARCH_URL,
        "sec-fetch-mode": "same-origin",
        "sec-fetch-site": "same-origin",
    }
    for attempt in range(TRIPADVISOR_GRAPHQL_MAX_RETRIES):
        try:
            response = await page.context.request.post(
                TRIPADVISOR_HOTEL_GRAPHQL_URL,
                data=json.dumps(payload),
                headers=headers,
                timeout=120_000,
            )
        except Exception as error:
            print(f"[TRIPADVISOR][HOTELS] GraphQL request failed: {error}")
            if attempt + 1 >= TRIPADVISOR_GRAPHQL_MAX_RETRIES:
                return TripadvisorGraphQLResult([], 0, {}, failed=True)
            await page.wait_for_timeout(1000 * (2 ** attempt))
            continue

        if response.ok:
            try:
                data = await response.json()
            except Exception as error:
                print(f"[TRIPADVISOR][HOTELS] Unexpected GraphQL JSON: {error}")
                return TripadvisorGraphQLResult([], 0, {}, failed=True)
            result_nodes = tripadvisor_hotel_results(data)
            source = result_nodes if result_nodes else data
            cards = extract_graphql_hotel_cards(source)
            return TripadvisorGraphQLResult(
                cards=cards,
                raw_count=len(result_nodes) if result_nodes else len(cards),
                metadata=tripadvisor_hotel_metadata(data),
            )

        if response.status == 403:
            print("[TRIPADVISOR][HOTELS] GraphQL access refused/challenged: 403")
            return TripadvisorGraphQLResult([], 0, {}, blocked=True)
        if response.status == 429:
            print(f"[TRIPADVISOR][HOTELS] GraphQL rate limited: 429 attempt {attempt + 1}")
            if attempt + 1 >= TRIPADVISOR_GRAPHQL_MAX_RETRIES:
                return TripadvisorGraphQLResult([], 0, {}, failed=True)
            await page.wait_for_timeout(2000 * (2 ** attempt))
            continue
        if 500 <= response.status < 600:
            print(
                f"[TRIPADVISOR][HOTELS] GraphQL server error: "
                f"{response.status} attempt {attempt + 1}"
            )
            if attempt + 1 >= TRIPADVISOR_GRAPHQL_MAX_RETRIES:
                return TripadvisorGraphQLResult([], 0, {}, failed=True)
            await page.wait_for_timeout(1500 * (2 ** attempt))
            continue

        print(
            f"[TRIPADVISOR][HOTELS] GraphQL failed: "
            f"{response.status} {response.status_text}"
        )
        return TripadvisorGraphQLResult([], 0, {}, failed=True)

    return TripadvisorGraphQLResult([], 0, {}, failed=True)


async def fetch_tripadvisor_hotel_graphql_page(
    page: Page,
    page_number: int,
) -> list[dict[str, Any]]:
    result = await fetch_tripadvisor_hotel_graphql_result(page, page_number)
    return result.cards


async def wait_for_tripadvisor_content(
    page: Page,
    marker_selector: str,
    label: str,
) -> dict[str, Any]:
    for attempt in range(2):
        for _ in range(6):
            try:
                await accept_cookies(page)
                await page.wait_for_load_state("load", timeout=10_000)
            except Exception:
                pass
            try:
                await page.evaluate(
                    'window.scrollTo({top: Math.min(document.body.scrollHeight, 1800), behavior: "smooth"})'
                )
            except Exception:
                pass
            await page.wait_for_timeout(2500)
            debug = await collect_page_debug(
                page,
                {
                    "target_links": marker_selector,
                    "links": "a",
                    "images": "img",
                },
                text_limit=900,
            )
            counts = debug.get("counts") if isinstance(debug.get("counts"), dict) else {}
            if int(counts.get("target_links") or 0) > 0:
                return debug
            if int(counts.get("links") or 0) > 0 and int(debug.get("body_length") or 0) > 300:
                return debug

        if attempt == 0:
            print(f"[TRIPADVISOR] {label}: no content detected yet; reloading once.")
            try:
                await page.reload(wait_until="load", timeout=120_000)
            except Exception:
                pass

    print(
        f"[TRIPADVISOR] {label}: page still has no usable links. "
        "If the browser shows a blank page, consent screen, or verification, complete it and rerun."
    )
    return await collect_page_debug(
        page,
        {
            "target_links": marker_selector,
            "links": "a",
            "images": "img",
        },
        text_limit=900,
    )


def parse_number(value: Any) -> int | None:
    if value in (None, ""):
        return None
    match = re.search(r"[\d,]+", str(value))
    if not match:
        return None
    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_price(value: Any) -> tuple[float | None, str | None]:
    text = str(value or "")
    match = re.search(r"(US\$|USD|TZS|\$|€|£)\s*([\d,.]+)", text, flags=re.IGNORECASE)
    if not match:
        return None, None
    symbol = match.group(1).upper()
    currency = {
        "$": "USD",
        "US$": "USD",
        "USD": "USD",
        "TZS": "TZS",
        "€": "EUR",
        "£": "GBP",
    }.get(symbol, symbol[:3])
    return parse_float(match.group(2)), currency


def tripadvisor_id_from_url(url: Any) -> str | None:
    match = re.search(r"-d(\d+)-", str(url or ""))
    return match.group(1) if match else None


def valid_tripadvisor_location_id(value: Any) -> str | None:
    text = clean_text(value)
    return text if text and re.fullmatch(r"\d+", text) else None


async def fetch_static_html(page: Page, url: str) -> str:
    try:
        response = await page.context.request.get(
            url,
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "accept-language": "en-US,en;q=0.9",
            },
            timeout=120_000,
        )
        if not response.ok:
            print(
                f"[TRIPADVISOR] Static fetch failed: "
                f"{response.status} {response.status_text}"
            )
            return ""
        return await response.text()
    except Exception as error:
        print(f"[TRIPADVISOR] Static fetch failed: {error}")
        return ""


def text_from_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return clean_text(html.unescape(without_tags)) or ""


def name_from_tripadvisor_url(url: Any) -> str | None:
    match = re.search(r"Reviews(?:-or\d+)?-([^-]+(?:-[^-]+)*)-", str(url or ""))
    if not match:
        return None
    name = match.group(1).replace("_", " ").replace("-", " ")
    return clean_text(name)


def extract_static_cards_from_html(html_text: str, marker: str) -> list[dict[str, Any]]:
    cards_by_url: dict[str, dict[str, Any]] = {}
    if not html_text:
        return []
    href_pattern = re.compile(
        rf'href=["\']([^"\']*{re.escape(marker)}[^"\']*)["\']',
        flags=re.IGNORECASE,
    )
    for match in href_pattern.finditer(html_text):
        url = normalize_tripadvisor_url(html.unescape(match.group(1)))
        if not url or url in cards_by_url:
            continue
        start = max(0, match.start() - 1800)
        end = min(len(html_text), match.end() + 1800)
        context = html_text[start:end]
        text = text_from_html(context)
        name = name_from_tripadvisor_url(url)
        image_match = re.search(
            r'(?:src|data-lazyurl|data-src)=["\']([^"\']+\.(?:jpg|jpeg|png|webp)[^"\']*)["\']',
            context,
            flags=re.IGNORECASE,
        )
        rating_match = re.search(r"(\d+(?:\.\d+)?)\s+of\s+5\s+bubbles", text, flags=re.IGNORECASE)
        review_match = re.search(r"([\d,]+)\s+reviews?", text, flags=re.IGNORECASE)
        price_match = re.search(r"(US\$|USD|TZS|\$|€|£)\s*[\d,.]+", text, flags=re.IGNORECASE)
        cards_by_url[url] = {
            "name": name,
            "url": url,
            "image": normalize_tripadvisor_url(html.unescape(image_match.group(1))) if image_match else None,
            "text": text,
            "rating": rating_match.group(0) if rating_match else None,
            "review_count": review_match.group(0) if review_match else None,
            "price": price_match.group(0) if price_match else None,
        }
    return list(cards_by_url.values())


def first_text_for_keys(value: Any, keys: set[str]) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in keys:
                text = clean_text(child)
                if text:
                    return text
        for child in value.values():
            text = first_text_for_keys(child, keys)
            if text:
                return text
    elif isinstance(value, list):
        for child in value:
            text = first_text_for_keys(child, keys)
            if text:
                return text
    return None


def first_number_for_keys(value: Any, keys: set[str]) -> int | float | None:
    text = first_text_for_keys(value, keys)
    if text is None:
        return None
    parsed_float = parse_float(text)
    parsed_int = parse_number(text)
    return parsed_int if parsed_int is not None and "." not in text else parsed_float


def find_tripadvisor_hotel_url(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if key_text in {"url", "detailurl", "canonicalurl", "commerceurl", "weburl"}:
                url = normalize_tripadvisor_url(child)
                if url and "Hotel_Review-" in url:
                    return url
            found = find_tripadvisor_hotel_url(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_tripadvisor_hotel_url(child)
            if found:
                return found
    elif isinstance(value, str) and "Hotel_Review-" in value:
        return normalize_tripadvisor_url(value)
    return None


def graph_node_candidates(value: Any) -> list[dict[str, Any]]:
    candidates = []
    if isinstance(value, dict):
        if find_tripadvisor_hotel_url(value):
            candidates.append(value)
        for child in value.values():
            candidates.extend(graph_node_candidates(child))
    elif isinstance(value, list):
        for child in value:
            candidates.extend(graph_node_candidates(child))
    return candidates


def extract_graphql_hotel_cards(payload: Any) -> list[dict[str, Any]]:
    cards_by_url: dict[str, dict[str, Any]] = {}
    for node in graph_node_candidates(payload):
        url = find_tripadvisor_hotel_url(node)
        if not url:
            continue
        name = first_text_for_keys(
            node,
            {
                "name",
                "title",
                "localizedname",
                "displayname",
                "locationname",
                "commercehotelname",
            },
        )
        if not name:
            name = name_from_tripadvisor_url(url)
        if not name:
            continue

        image = first_text_for_keys(
            node,
            {"photo", "image", "imageurl", "thumbnail", "thumbnailurl", "urltemplate"},
        )
        rating = first_number_for_keys(
            node,
            {"rating", "bubblerating", "averagerating", "reviewscore", "score"},
        )
        review_count = first_number_for_keys(
            node,
            {"reviewcount", "reviewscount", "numreviews", "userreviewcount"},
        )
        price = first_text_for_keys(
            node,
            {"price", "priceforstay", "displayprice", "price_string", "commerceprice"},
        )
        text = text_from_html(json.dumps(node, ensure_ascii=False))
        location_id = valid_tripadvisor_location_id(
            tripadvisor_location_id_from_node(node)
        ) or tripadvisor_id_from_url(url)
        cards_by_url[url] = {
            "name": name,
            "url": url,
            "location_id": location_id,
            "image": image,
            "text": text,
            "rating": rating,
            "review_count": review_count,
            "price": price,
            "raw": node,
        }
    return list(cards_by_url.values())


def normalize_tripadvisor_url(url: Any) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    return urljoin("https://www.tripadvisor.com", url.strip())


def clean_text(value: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or None


def extract_amenities_from_text(text: str) -> str | None:
    candidates = [
        "Free Wifi",
        "Breakfast included",
        "Pool",
        "Restaurant",
        "Beachfront",
        "Airport transportation",
        "Free parking",
        "Spa",
        "Fitness center",
        "Bar/Lounge",
        "Room service",
        "Air conditioning",
        "Family rooms",
        "Non-smoking rooms",
    ]
    found = [amenity for amenity in candidates if amenity.lower() in text.lower()]
    return join_values(found)


def normalize_card(raw: dict[str, Any]) -> dict[str, Any] | None:
    url = normalize_tripadvisor_url(raw.get("url"))
    name = clean_text(raw.get("name"))
    if not url or not name:
        return None
    name = re.sub(r"^\d+\.\s*", "", name).strip()
    if re.search(r"\bbubbles?\b", name, flags=re.IGNORECASE):
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?(?:\s+\d+(?:\.\d+)?)?.*", name):
        return None

    text = clean_text(raw.get("text")) or ""
    price, currency = parse_price(text)
    rating = first_nonempty(raw.get("rating"), parse_float(text))
    review_count = first_nonempty(raw.get("review_count"), parse_number(text))
    tripadvisor_id = valid_tripadvisor_location_id(
        raw.get("location_id")
    ) or tripadvisor_id_from_url(url)
    if not tripadvisor_id:
        print(f"[TRIPADVISOR][HOTELS] Skipping {name}: missing numeric locationId")
        return None

    return {
        "source": TRIPADVISOR_SOURCE_ID,
        "tripadvisor_id": tripadvisor_id,
        "location_id": tripadvisor_id,
        "source_place_id": tripadvisor_id,
        "hotel_id": tripadvisor_id,
        "name": name,
        "property_url": url,
        "source_url": url,
        "address": clean_text(raw.get("address")),
        "city": "Zanzibar City",
        "country_code": "TZ",
        "latitude": raw.get("latitude"),
        "longitude": raw.get("longitude"),
        "display_location": clean_text(raw.get("location")),
        "review_score": rating,
        "review_count": review_count,
        "star_rating": raw.get("star_rating"),
        "description": clean_text(raw.get("description")),
        "description_summary": clean_text(raw.get("description")),
        "photo_url": normalize_tripadvisor_url(raw.get("image")),
        "gallery_photo_urls": [
            url
            for url in [normalize_tripadvisor_url(raw.get("image"))]
            if url
        ],
        "full_facilities": first_nonempty(
            clean_text(raw.get("amenities")),
            extract_amenities_from_text(text),
        ),
        "property_badges": clean_text(raw.get("badges")),
        "price": price,
        "currency": currency,
        "checkin": CHECKIN,
        "checkout": CHECKOUT,
        "sold_out": False,
        "raw": raw,
        "catalog_parse_method": raw.get("parse_method") or "graphql",
    }


async def extract_search_cards(page: Page) -> list[dict[str, Any]]:
    return await page.evaluate(
        """
        () => {
            const text = (node) => (node?.innerText || node?.textContent || '').trim();
            const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
            const looksLikeName = (value) => {
                const text = clean(value);
                if (text.length < 3 || text.length > 120) return false;
                if (!/[A-Za-z]/.test(text)) return false;
                if (/\\bbubbles?\\b|reviews?|availability|view deal|show prices|sponsored|ad\\s/i.test(text)) return false;
                if (/^\\d+(\\.\\d+)?(?:\\s+\\d+(\\.\\d+)?)?/.test(text)) return false;
                if (/(US\\$|USD|TZS|\\$|€|£)\\s*\\d/i.test(text)) return false;
                return true;
            };
            const nameFromUrl = (url) => {
                const match = String(url || '').match(/Reviews-([^-]+(?:-[^-]+)*)-/);
                if (!match) return '';
                return match[1].replace(/_/g, ' ').replace(/-/g, ' ').trim();
            };
            const absolute = (href) => {
                try { return new URL(href, location.origin).href; }
                catch (_) { return null; }
            };
            const usefulAncestor = (anchor) => {
                let node = anchor;
                for (let depth = 0; node && depth < 8; depth += 1, node = node.parentElement) {
                    const value = text(node);
                    if (
                        value.length >= 60 &&
                        value.length <= 6000 &&
                        /review|availability|value|hotel|resort|guest|lodge|inn/i.test(value)
                    ) {
                        return node;
                    }
                }
                return anchor.closest('article, section, div') || anchor;
            };
            const anchors = [...document.querySelectorAll('a[href*="Hotel_Review-"]')];
            const byUrl = new Map();
            const cards = [];

            for (const anchor of anchors) {
                const url = absolute(anchor.getAttribute('href'));
                if (!url) continue;

                const root = usefulAncestor(anchor);
                const rootText = text(root);
                const lines = rootText.split('\\n').map((line) => line.trim()).filter(Boolean);
                const selectorNames = [
                    text(root.querySelector('h1, h2, h3')),
                    text(root.querySelector('[data-test-target*="property-name"], [data-test-target*="hotel-name"], [class*="property"], [class*="title"]'))
                ].filter(looksLikeName);
                const lineNames = lines
                    .map((line) => line.replace(/^\\d+\\.\\s*/, '').trim())
                    .filter(looksLikeName);
                const anchorText = text(anchor).replace(/^\\d+\\.\\s*/, '').trim();
                const anchorName = looksLikeName(anchorText) ? anchorText : '';
                const name = selectorNames[0] || anchorName || lineNames[0] || nameFromUrl(url);
                const image = root.querySelector('img')?.currentSrc ||
                    root.querySelector('img')?.src ||
                    root.querySelector('img')?.getAttribute('data-lazyurl') ||
                    root.querySelector('img')?.getAttribute('data-src');
                const ratingLabel = root.querySelector('[aria-label*="bubble"], [aria-label*="rating"]')?.getAttribute('aria-label') || '';
                const reviewText = lines.find((line) => /review/i.test(line) && /\\d/.test(line)) || '';
                const priceText = lines.find((line) => /(US\\$|USD|TZS|\\$|€|£)\\s*\\d/i.test(line)) || '';

                const candidate = {
                    name,
                    url,
                    image,
                    text: rootText,
                    rating: ratingLabel,
                    review_count: reviewText,
                    price: priceText
                };
                const existing = byUrl.get(url);
                if (!existing || (looksLikeName(candidate.name) && candidate.text.length > existing.text.length)) {
                    byUrl.set(url, candidate);
                }
            }
            for (const card of byUrl.values()) {
                const fallbackName = nameFromUrl(card.url);
                const name = looksLikeName(card.name) ? card.name : fallbackName;
                if (looksLikeName(name)) cards.push({...card, name});
            }
            return cards;
        }
        """
    )


async def scrape_tripadvisor_detail_page(
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
    except Exception as error:
        print(f"[TRIPADVISOR] Detail page failed for {hotel.get('name')}: {error}")
        return {}

    try:
        data = await page.evaluate(
            """
            () => {
                const text = (node) => (node?.innerText || node?.textContent || '').trim();
                const unique = (items) => [...new Set(items.map((item) => (item || '').trim()).filter(Boolean))];
                const bodyText = document.body?.innerText || '';
                const scripts = [...document.scripts].map((script) => script.textContent || '').join('\\n');
                const metaDescription = document.querySelector('meta[name="description"]')?.content || '';
                const title = text(document.querySelector('h1')) ||
                    (document.title || '').replace(/ - Tripadvisor.*$/i, '').trim();
                const address = text(document.querySelector('[itemprop="address"], address, [data-test-target*="address"]'));
                const amenities = unique(
                    [...document.querySelectorAll('[data-test-target*="amenity"], [class*="amenity"], li')]
                        .map(text)
                        .filter((value) => value.length > 2 && value.length < 80)
                ).slice(0, 40);
                const images = unique(
                    [...document.images]
                        .map((img) => img.currentSrc || img.src || img.getAttribute('data-lazyurl') || img.getAttribute('data-src'))
                        .filter((src) => src && /^https?:/.test(src))
                ).slice(0, 20);
                return {bodyText, scripts, metaDescription, title, address, amenities, images};
            }
            """
        )
    except Exception as error:
        print(f"[TRIPADVISOR] Failed to parse detail page for {hotel.get('name')}: {error}")
        return {}

    if not isinstance(data, dict):
        return {}

    combined = "\n".join(
        str(data.get(key) or "")
        for key in ["scripts", "bodyText"]
    )
    latitude = first_nonempty(
        re.search(r'"latitude"\s*:\s*"?(-?\d+(?:\.\d+)?)"?', combined),
        re.search(r'"lat"\s*:\s*"?(-?\d+(?:\.\d+)?)"?', combined),
    )
    longitude = first_nonempty(
        re.search(r'"longitude"\s*:\s*"?(-?\d+(?:\.\d+)?)"?', combined),
        re.search(r'"lng"\s*:\s*"?(-?\d+(?:\.\d+)?)"?', combined),
    )
    images = data.get("images") if isinstance(data.get("images"), list) else []
    amenities = data.get("amenities") if isinstance(data.get("amenities"), list) else []

    return {
        "name": clean_text(data.get("title")) or hotel.get("name"),
        "address": clean_text(data.get("address")) or hotel.get("address"),
        "description": clean_text(data.get("metaDescription")) or hotel.get("description"),
        "description_summary": clean_text(data.get("metaDescription")) or hotel.get("description_summary"),
        "full_facilities": join_values(amenities) or hotel.get("full_facilities"),
        "photo_url": hotel.get("photo_url") or (images[0] if images else None),
        "gallery_photo_urls": images or hotel.get("gallery_photo_urls") or [],
        "latitude": parse_float(latitude.group(1)) if latitude else hotel.get("latitude"),
        "longitude": parse_float(longitude.group(1)) if longitude else hotel.get("longitude"),
    }


async def enrich_tripadvisor_hotels_with_detail_pages(
    context: BrowserContext,
    hotels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not hotels:
        return hotels

    print("[TRIPADVISOR] Enriching hotel detail pages...")
    page = await context.new_page()
    enriched = []
    try:
        for index, hotel in enumerate(hotels, start=1):
            print(f"[TRIPADVISOR] Detail {index}/{len(hotels)}: {hotel.get('name')}")
            details = await scrape_tripadvisor_detail_page(page, hotel)
            enriched.append({**hotel, **details})
            await page.wait_for_timeout(1000)
    finally:
        await page.close()
    return enriched


def dedupe_tripadvisor_hotels(hotels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for hotel in hotels:
        key = str(hotel.get("tripadvisor_id") or "").strip()
        if not key:
            key = safe_filename(
                f"{hotel.get('name')}_{hotel.get('latitude')}_{hotel.get('longitude')}"
            )
        unique.setdefault(key, hotel)
    return list(unique.values())


async def scrape_tripadvisor_hotels_in_context(
    context: BrowserContext,
    catalog_mode: bool = False,
) -> list[dict[str, Any]]:
    del catalog_mode
    page = context.pages[0] if context.pages else await context.new_page()
    all_hotels: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_location_ids: set[str] = set()
    seen_page_fingerprints: set[tuple[str, ...]] = set()
    page_stats: list[TripadvisorHotelPageStat] = []
    consecutive_low_new_pages = 0
    stop_reason = "page iterator exhausted"

    print_category_header("Tripadvisor", "Hotels")

    for page_number in tripadvisor_hotel_page_numbers():
        offset = (page_number - 1) * TRIPADVISOR_RESULTS_PER_PAGE
        graphql_result = await fetch_tripadvisor_hotel_graphql_result(page, page_number)
        if graphql_result.blocked or graphql_result.failed:
            stop_reason = "GraphQL failure"
            print("[TRIPADVISOR][HOTELS] Collection stopped by GraphQL failure")
            break
        raw_cards = graphql_result.cards
        if graphql_result.raw_count == 0 or not raw_cards:
            stop_reason = "empty results"
            page_stats.append(
                TripadvisorHotelPageStat(
                    offset=offset,
                    raw_count=graphql_result.raw_count,
                    new_unique=0,
                    total_unique=len(all_hotels),
                    metadata=graphql_result.metadata,
                )
            )
            print_catalog_page(
                page_number=page_number,
                offset=offset,
                received=graphql_result.raw_count,
                new=0,
                total_unique=len(all_hotels),
                suffix=format_tripadvisor_hotel_metadata(graphql_result.metadata),
            )
            print("[TRIPADVISOR][HOTELS] Collection complete")
            break

        page_fingerprint = tripadvisor_hotel_page_fingerprint(raw_cards)
        repeated_page = page_fingerprint and page_fingerprint in seen_page_fingerprints

        page_hotels = []
        for raw_card in raw_cards:
            try:
                hotel = normalize_card(raw_card)
                if not hotel:
                    continue
                location_id = str(hotel.get("tripadvisor_id") or "").strip()
                if location_id and location_id in seen_location_ids:
                    continue
                if not location_id and hotel["property_url"] in seen_urls:
                    continue
                if location_id:
                    seen_location_ids.add(location_id)
                seen_urls.add(hotel["property_url"])
                page_hotels.append(hotel)
            except Exception as error:
                print(f"[TRIPADVISOR] Failed to parse one property: {error}")

        print_catalog_page(
            page_number=page_number,
            offset=offset,
            received=graphql_result.raw_count,
            new=len(page_hotels),
            total_unique=len(all_hotels) + len(page_hotels),
            suffix=format_tripadvisor_hotel_metadata(graphql_result.metadata),
        )
        page_stats.append(
            TripadvisorHotelPageStat(
                offset=offset,
                raw_count=graphql_result.raw_count,
                new_unique=len(page_hotels),
                total_unique=len(all_hotels) + len(page_hotels),
                metadata=graphql_result.metadata,
            )
        )
        if repeated_page:
            stop_reason = "repeated page fingerprint"
            print(
                "[TRIPADVISOR][HOTELS] Collection stopped: "
                "repeated page fingerprint"
            )
            break
        if page_fingerprint:
            seen_page_fingerprints.add(page_fingerprint)
        if not page_hotels:
            stop_reason = "zero new locationIds"
            print("[TRIPADVISOR][HOTELS] Collection complete")
            break

        all_hotels.extend(page_hotels)

        if len(page_hotels) < 3:
            consecutive_low_new_pages += 1
        else:
            consecutive_low_new_pages = 0
        if consecutive_low_new_pages >= 3:
            stop_reason = (
                "Tripadvisor appears to be recycling catalogue results "
                "after 3 low-new pages"
            )
            print(
                "[TRIPADVISOR][HOTELS] Collection stopped: Tripadvisor "
                "appears to be recycling catalogue results"
            )
            break
        await page.wait_for_timeout(1500)

    unique_hotels = dedupe_tripadvisor_hotels(all_hotels)
    print("[TRIPADVISOR][HOTELS] Collection complete")
    print_catalog_complete("Hotels", len(unique_hotels))
    print_tripadvisor_hotel_catalog_summary(page_stats, stop_reason)
    return unique_hotels
