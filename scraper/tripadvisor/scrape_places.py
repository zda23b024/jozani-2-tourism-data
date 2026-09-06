import itertools
import json
import re
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

from playwright.async_api import BrowserContext, Page

from config.configuration import (
    ADULTS,
    CHECKIN,
    CHILDREN,
    MAX_TRIPADVISOR_PLACE_PAGES,
    TRIPADVISOR_ATTRACTIONS_GRAPHQL_ENABLED,
    TRIPADVISOR_ATTRACTIONS_GRAPHQL_QUERY_ID,
    TRIPADVISOR_ATTRACTIONS_GRAPHQL_URL,
    TRIPADVISOR_ATTRACTIONS_SORT,
    TRIPADVISOR_ATTRACTIONS_URL,
    TRIPADVISOR_FIND_RESTAURANTS_URL,
    TRIPADVISOR_GEO_ID,
    TRIPADVISOR_RESTAURANTS_URL,
    TRIPADVISOR_RESTAURANTS_GRAPHQL_ENABLED,
    TRIPADVISOR_RESTAURANTS_GRAPHQL_QUERY_ID,
    TRIPADVISOR_RESTAURANTS_GRAPHQL_URL,
    TRIPADVISOR_RESTAURANTS_LOCALE,
    TRIPADVISOR_RESULTS_PER_PAGE,
)
from config.configuration import OUTPUT_DIR
from utils.browser_helpers import accept_cookies
from utils.console_output import (
    print_catalog_complete,
    print_catalog_page,
    print_category_header,
)
from utils.helpers import first_nonempty, join_values, safe_filename
from scraper.tripadvisor.scrape_stays import (
    TripadvisorGraphQLResult,
    clean_text,
    extract_static_cards_from_html,
    fetch_static_html,
    graphql_response_items,
    nested_value,
    parse_float,
    parse_number,
    parse_price,
    tripadvisor_cookie_value,
    tripadvisor_location_id_from_node,
    valid_tripadvisor_location_id,
    wait_for_tripadvisor_content,
)


TRIPADVISOR_SOURCE_ID = "tripadvisor"
TRIPADVISOR_ATTRACTION_PAGINATION_CONFIRMED = True
TRIPADVISOR_RESTAURANT_PAGINATION_CONFIRMED = True
ATTRACTION_PAGINATION_DEBUG_DIR = OUTPUT_DIR / "debug" / "tripadvisor" / "attraction_pagination"


def tripadvisor_pagination_confirmed(kind: str) -> bool:
    if kind == "attractions":
        return TRIPADVISOR_ATTRACTION_PAGINATION_CONFIRMED
    if kind == "restaurants":
        return TRIPADVISOR_RESTAURANT_PAGINATION_CONFIRMED
    return True


def tripadvisor_place_page_numbers() -> range | itertools.count:
    from config.configuration import TRIPADVISOR_CATALOG_TEST_FIRST_PAGE_ONLY

    if TRIPADVISOR_CATALOG_TEST_FIRST_PAGE_ONLY:
        return range(1, 2)
    if MAX_TRIPADVISOR_PLACE_PAGES is None:
        return itertools.count(1)
    return range(1, MAX_TRIPADVISOR_PLACE_PAGES + 1)


def graph_node_candidates(value: Any, detail_marker: str) -> list[dict[str, Any]]:
    candidates = []
    if isinstance(value, dict):
        if find_tripadvisor_place_url(value, detail_marker):
            candidates.append(value)
        for child in value.values():
            candidates.extend(graph_node_candidates(child, detail_marker))
    elif isinstance(value, list):
        for child in value:
            candidates.extend(graph_node_candidates(child, detail_marker))
    return candidates


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


def find_tripadvisor_place_url(value: Any, detail_marker: str) -> str | None:
    marker = detail_marker.lstrip("/")
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if key_text in {"url", "detailurl", "canonicalurl", "weburl", "routeurl"}:
                url = normalize_url(child)
                if url and marker in url:
                    return url
            found = find_tripadvisor_place_url(child, detail_marker)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_tripadvisor_place_url(child, detail_marker)
            if found:
                return found
    elif isinstance(value, str) and marker in value:
        return normalize_url(value)
    return None


def extract_graphql_place_cards(payload: Any, detail_marker: str) -> list[dict[str, Any]]:
    cards_by_url: dict[str, dict[str, Any]] = {}
    for node in graph_node_candidates(payload, detail_marker):
        url = find_tripadvisor_place_url(node, detail_marker)
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
                "commerceattractionname",
                "restaurantname",
            },
        ) or place_name_from_url(url)
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
            {"price", "displayprice", "price_string", "fromprice", "commerceprice"},
        )
        text = re.sub(r"\s+", " ", json.dumps(node, ensure_ascii=False))
        location_id = valid_tripadvisor_location_id(
            tripadvisor_location_id_from_node(node)
        ) or place_id_from_url(url)
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


def result_nodes_for_marker(payload: Any, detail_marker: str) -> list[dict[str, Any]]:
    marker = detail_marker.lstrip("/")
    results: list[dict[str, Any]] = []
    for item in graphql_response_items(payload):
        for path in [
            ("data", "list", "results"),
            ("data", "results"),
            ("data", "restaurants", "results"),
            ("data", "attractions", "results"),
        ]:
            value = nested_value(item, *path)
            if isinstance(value, list):
                results.extend(
                    node
                    for node in value
                    if isinstance(node, dict) and marker in json.dumps(node, ensure_ascii=False)
                )
    return results or graph_node_candidates(payload, detail_marker)


def metadata_for_marker(payload: Any) -> dict[str, Any]:
    for item in graphql_response_items(payload):
        for path in [
            ("data", "list", "searchMetadata"),
            ("data", "list", "metadata"),
            ("data", "metadata"),
            ("data", "pagination"),
        ]:
            value = nested_value(item, *path)
            if isinstance(value, dict):
                return value
    return {}


def restaurant_response_object(payload: Any) -> dict[str, Any]:
    for item in graphql_response_items(payload):
        value = nested_value(item, "data", "response")
        if isinstance(value, dict):
            return value
    return {}


def restaurant_response_records(payload: Any) -> list[dict[str, Any]]:
    restaurants = restaurant_response_object(payload).get("restaurants")
    if not isinstance(restaurants, list):
        return []
    return [item for item in restaurants if isinstance(item, dict)]


def restaurant_response_metadata(payload: Any) -> dict[str, Any]:
    response = restaurant_response_object(payload)
    metadata = response.get("metadata")
    pagination = response.get("pagination")
    merged: dict[str, Any] = {}
    if isinstance(metadata, dict):
        merged.update(metadata)
    if isinstance(pagination, dict):
        merged["pagination"] = pagination
    return merged


def sanitized_tripadvisor_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, child in value.items():
            key_text = str(key).lower()
            if key_text in {"sessionid", "pageviewuid", "pageviewid"}:
                sanitized[key] = "<redacted>"
            else:
                sanitized[key] = sanitized_tripadvisor_value(child)
        return sanitized
    if isinstance(value, list):
        return [sanitized_tripadvisor_value(child) for child in value]
    return value


def dotted_path(path: tuple[str, ...]) -> str:
    return ".".join(path) if path else "$"


def attraction_response_list_paths(
    value: Any,
    path: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    paths: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            paths.extend(attraction_response_list_paths(child, (*path, str(key))))
    elif isinstance(value, list):
        sample = value[:5]
        marker_count = sum(
            1
            for item in value
            if isinstance(item, dict)
            and "/Attraction_Review-" in json.dumps(item, ensure_ascii=False)
        )
        paths.append(
            {
                "path": dotted_path(path),
                "length": len(value),
                "dict_items": sum(1 for item in value if isinstance(item, dict)),
                "attraction_marker_items": marker_count,
                "sample_keys": [
                    list(item.keys())[:12]
                    for item in sample
                    if isinstance(item, dict)
                ],
            }
        )
        for index, child in enumerate(sample):
            paths.extend(attraction_response_list_paths(child, (*path, f"[{index}]")))
    return paths


def attraction_response_pagination_values(value: Any) -> dict[str, list[dict[str, Any]]]:
    keys = {
        "updatetoken",
        "cursor",
        "nextcursor",
        "next_cursor",
        "pagetoken",
        "page_token",
        "paginationlinkslist",
        "hasnext",
        "hasnextpage",
        "page",
        "offset",
        "token",
    }
    found: dict[str, list[dict[str, Any]]] = {}

    def walk(child: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(child, dict):
            for key, value_for_key in child.items():
                key_text = str(key).lower()
                if key_text in keys:
                    found.setdefault(str(key), []).append(
                        {
                            "path": dotted_path((*path, str(key))),
                            "value": sanitized_tripadvisor_value(value_for_key),
                        }
                    )
                walk(value_for_key, (*path, str(key)))
        elif isinstance(child, list):
            for index, item in enumerate(child[:5]):
                walk(item, (*path, f"[{index}]"))

    walk(value)
    return found


def attraction_result_object(payload: Any) -> dict[str, Any]:
    for item in graphql_response_items(payload):
        result = nested_value(item, "data", "Result")
        if isinstance(result, list) and result and isinstance(result[0], dict):
            return result[0]
    return {}


def attraction_result_sections(payload: Any) -> list[dict[str, Any]]:
    result = attraction_result_object(payload)
    sections = result.get("sections")
    if not isinstance(sections, list):
        return []
    return [section for section in sections if isinstance(section, dict)]


def section_route_page(section: dict[str, Any]) -> Any:
    return nested_value(section, "singleFlexCardContent", "cardLink", "webRoute", "page")


def section_route_parameters(section: dict[str, Any]) -> Any:
    return nested_value(
        section,
        "singleFlexCardContent",
        "cardLink",
        "webRoute",
        "routeParameters",
    )


def is_attraction_card_section(section: dict[str, Any]) -> bool:
    if not section.get("singleFlexCardContent"):
        return False
    if section_route_page(section) == "Attraction_Review":
        return True
    return "/Attraction_Review-" in json.dumps(section, ensure_ascii=False)


def attraction_card_sections(payload: Any) -> list[dict[str, Any]]:
    return [
        section
        for section in attraction_result_sections(payload)
        if is_attraction_card_section(section)
    ]


def attraction_total_results(payload: Any) -> Any:
    return attraction_result_object(payload).get("totalResults")


def section_navigation_fragments(section: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(section, ensure_ascii=False).lower()
    if not any(
        marker in text
        for marker in [
            "pagination",
            "next",
            "webroute",
            "routeparameters",
            "updatetoken",
            "cursor",
            "loadmore",
            "continuation",
        ]
    ):
        return {}
    return {
        "pagination_like_fields": attraction_response_pagination_values(section),
        "route_parameters": sanitized_tripadvisor_value(section_route_parameters(section)),
    }


def attraction_section_debug(section: dict[str, Any], index: int) -> dict[str, Any]:
    url = find_tripadvisor_place_url(section, "/Attraction_Review-")
    return {
        "index": index,
        "__typename": section.get("__typename"),
        "sectionType": section.get("sectionType"),
        "clusterId": section.get("clusterId"),
        "sectionId": section.get("sectionId"),
        "stableDiffingType": section.get("stableDiffingType"),
        "has_singleFlexCardContent": bool(section.get("singleFlexCardContent")),
        "cardLink_webRoute_page": section_route_page(section),
        "extracted_location_id": valid_tripadvisor_location_id(
            tripadvisor_location_id_from_node(section)
        ) or place_id_from_url(url),
        "attraction_url": url,
        "navigation": section_navigation_fragments(section),
    }


def reset_attraction_pagination_debug() -> None:
    if not ATTRACTION_PAGINATION_DEBUG_DIR.exists():
        return
    for path in ATTRACTION_PAGINATION_DEBUG_DIR.glob("page_*.json"):
        path.unlink(missing_ok=True)
    (ATTRACTION_PAGINATION_DEBUG_DIR / "count_mismatch_summary.json").unlink(missing_ok=True)


def save_attraction_pagination_diagnostics(
    page_number: int,
    request_payload: list[dict[str, Any]],
    response_payload: Any,
    result_nodes: list[dict[str, Any]],
    cards: list[dict[str, Any]],
) -> None:
    ATTRACTION_PAGINATION_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = ATTRACTION_PAGINATION_DEBUG_DIR / f"page_{page_number}.json"
    path.write_text(
        json.dumps(
            {
                "page_number": page_number,
                "request_variables": sanitized_tripadvisor_value(
                    request_payload[0].get("variables", {})
                    if request_payload and isinstance(request_payload[0], dict)
                    else {}
                ),
                "request_extensions": sanitized_tripadvisor_value(
                    request_payload[0].get("extensions", {})
                    if request_payload and isinstance(request_payload[0], dict)
                    else {}
                ),
                "recursive_marker_nodes": len(result_nodes),
                "result_sections": len(attraction_result_sections(response_payload)),
                "attraction_card_sections": len(attraction_card_sections(response_payload)),
                "unique_card_urls_extracted": len(cards),
                "api_reported_total_results": attraction_total_results(response_payload),
                "normalized_cards": sanitized_tripadvisor_value(cards),
                "sections": [
                    attraction_section_debug(section, index)
                    for index, section in enumerate(
                        attraction_result_sections(response_payload)
                    )
                ],
                "pagination_like_response_fields": attraction_response_pagination_values(
                    attraction_result_object(response_payload) or response_payload
                ),
                "response_list_paths_with_attraction_markers": [
                    item
                    for item in attraction_response_list_paths(response_payload)
                    if item.get("attraction_marker_items")
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def place_metadata_complete(metadata: dict[str, Any], offset: int, raw_count: int) -> bool:
    total = first_nonempty(
        metadata.get("total_hits"),
        metadata.get("totalHits"),
        metadata.get("totalResults"),
        metadata.get("total_results"),
        metadata.get("totalCount"),
    )
    try:
        total_int = int(str(total).replace(",", ""))
    except (TypeError, ValueError):
        total_int = None
    if total_int is not None and offset + raw_count >= total_int:
        return True

    next_cursor = first_nonempty(metadata.get("nextCursor"), metadata.get("next_cursor"))
    if total_int is not None and not next_cursor and raw_count == 0:
        return True
    return False


async def post_tripadvisor_place_graphql(
    page: Page,
    url: str,
    payload: list[dict[str, Any]],
    referer: str,
    label: str,
) -> Any:
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "origin": "https://www.tripadvisor.com",
        "referer": referer,
        "sec-fetch-mode": "same-origin",
        "sec-fetch-site": "same-origin",
    }
    for attempt in range(3):
        try:
            response = await page.context.request.post(
                url,
                data=json.dumps(payload),
                headers=headers,
                timeout=120_000,
            )
        except Exception as error:
            print(f"[TRIPADVISOR][{label}] GraphQL request failed: {error}")
            if attempt == 2:
                return None
            await page.wait_for_timeout(1000 * (2 ** attempt))
            continue

        if response.ok:
            try:
                return await response.json()
            except Exception as error:
                print(f"[TRIPADVISOR][{label}] Unexpected GraphQL JSON: {error}")
                return None
        if response.status == 403:
            print(f"[TRIPADVISOR][{label}] GraphQL access refused/challenged: 403")
            return None
        if response.status == 429:
            print(f"[TRIPADVISOR][{label}] GraphQL rate limited: 429 attempt {attempt + 1}")
            if attempt == 2:
                return None
            await page.wait_for_timeout(2000 * (2 ** attempt))
            continue
        if 500 <= response.status < 600:
            print(f"[TRIPADVISOR][{label}] GraphQL server error: {response.status} attempt {attempt + 1}")
            if attempt == 2:
                return None
            await page.wait_for_timeout(1500 * (2 ** attempt))
            continue
        print(f"[TRIPADVISOR][{label}] GraphQL failed: {response.status} {response.status_text}")
        return None
    return None


async def tripadvisor_attractions_graphql_payload(
    page: Page,
    page_number: int,
) -> list[dict[str, Any]]:
    pageview_id = str(uuid4())
    session_id = (
        await tripadvisor_cookie_value(page.context, "TASID")
        or await tripadvisor_cookie_value(page.context, "TASession")
        or uuid4().hex.upper()
    )
    route_params = {
        "geoId": int(TRIPADVISOR_GEO_ID),
        "filters": [{"id": "allAttractions", "value": ["true"]}],
        "contentType": "attraction",
        "webVariant": "AttractionsFusion",
        "sort": TRIPADVISOR_ATTRACTIONS_SORT,
    }
    if page_number > 1:
        route_params["pagee"] = str((page_number - 1) * TRIPADVISOR_RESULTS_PER_PAGE)
    return [
        {
            "variables": {
                "request": {
                    "tracking": {
                        "screenName": "AttractionsFusion",
                        "pageviewUid": pageview_id,
                    },
                    "routeParameters": route_params,
                    "updateToken": None,
                },
                "commerce": {
                    "attractionCommerce": {
                        "pax": [{"ageBand": "ADULT", "count": ADULTS}],
                        "startDate": CHECKIN,
                        "endDate": CHECKIN,
                        "setByUser": True,
                    }
                },
                "tracking": {
                    "screenName": "AttractionsFusion",
                    "pageviewUid": pageview_id,
                },
                "sessionId": session_id,
                "unitLength": "MILES",
                "currency": "USD",
                "currentGeoPoint": None,
                "mapSurface": False,
                "debug": False,
                "polling": False,
            },
            "extensions": {
                "preRegisteredQueryId": TRIPADVISOR_ATTRACTIONS_GRAPHQL_QUERY_ID,
            },
        }
    ]


async def fetch_tripadvisor_attractions_graphql_result(
    page: Page,
    page_number: int,
) -> TripadvisorGraphQLResult:
    if not TRIPADVISOR_ATTRACTIONS_GRAPHQL_ENABLED:
        return TripadvisorGraphQLResult([], 0, {}, failed=True)
    if page_number == 1:
        reset_attraction_pagination_debug()
    payload = await tripadvisor_attractions_graphql_payload(page, page_number)
    data = await post_tripadvisor_place_graphql(
        page,
        TRIPADVISOR_ATTRACTIONS_GRAPHQL_URL,
        payload,
        TRIPADVISOR_ATTRACTIONS_URL,
        "ATTRACTIONS",
    )
    if data is None:
        return TripadvisorGraphQLResult([], 0, {}, failed=True)
    result_nodes = result_nodes_for_marker(data, "/Attraction_Review-")
    card_sections = attraction_card_sections(data)
    cards = extract_graphql_place_cards(card_sections, "/Attraction_Review-")
    save_attraction_pagination_diagnostics(
        page_number,
        payload,
        data,
        result_nodes,
        cards,
    )
    return TripadvisorGraphQLResult(
        cards=cards,
        raw_count=len(card_sections),
        metadata={
            **metadata_for_marker(data),
            "totalResults": attraction_total_results(data),
        },
    )


async def fetch_tripadvisor_attractions_graphql_page(
    page: Page,
    page_number: int,
) -> list[dict[str, Any]]:
    result = await fetch_tripadvisor_attractions_graphql_result(page, page_number)
    return result.cards


async def tripadvisor_restaurants_graphql_payload(
    page: Page,
    page_number: int,
) -> list[dict[str, Any]]:
    route_params: dict[str, Any] = {
        "geoId": int(TRIPADVISOR_GEO_ID),
        "broadened": False,
    }
    if page_number > 1:
        route_params["offset"] = str((page_number - 1) * TRIPADVISOR_RESULTS_PER_PAGE)
    return [
        {
            "variables": {
                "limit": TRIPADVISOR_RESULTS_PER_PAGE,
                "racRequest": None,
                "route": {
                    "page": "FindRestaurants",
                    "params": route_params,
                },
                "additionalSelections": [],
                "insertSponsoredListings": True,
                "avoidLSS": False,
                "locale": TRIPADVISOR_RESTAURANTS_LOCALE,
            },
            "extensions": {
                "preRegisteredQueryId": TRIPADVISOR_RESTAURANTS_GRAPHQL_QUERY_ID,
            },
        }
    ]


async def fetch_tripadvisor_restaurants_graphql_result(
    page: Page,
    page_number: int,
) -> TripadvisorGraphQLResult:
    if not TRIPADVISOR_RESTAURANTS_GRAPHQL_ENABLED:
        return TripadvisorGraphQLResult([], 0, {}, failed=True)
    payload = await tripadvisor_restaurants_graphql_payload(page, page_number)
    data = await post_tripadvisor_place_graphql(
        page,
        TRIPADVISOR_RESTAURANTS_GRAPHQL_URL,
        payload,
        TRIPADVISOR_FIND_RESTAURANTS_URL,
        "RESTAURANTS",
    )
    if data is None:
        return TripadvisorGraphQLResult([], 0, {}, failed=True)
    restaurant_records = restaurant_response_records(data)
    cards = extract_graphql_place_cards(restaurant_records, "/Restaurant_Review-")
    return TripadvisorGraphQLResult(
        cards=cards,
        raw_count=len(restaurant_records),
        metadata=restaurant_response_metadata(data),
    )


async def fetch_tripadvisor_restaurants_graphql_page(
    page: Page,
    page_number: int,
) -> list[dict[str, Any]]:
    result = await fetch_tripadvisor_restaurants_graphql_result(page, page_number)
    return result.cards


PLACE_CONFIGS = {
    "restaurants": {
        "label": "RESTAURANTS",
        "urls": [TRIPADVISOR_FIND_RESTAURANTS_URL, TRIPADVISOR_RESTAURANTS_URL],
        "detail_marker": "/Restaurant_Review-",
        "id_field": "restaurant_id",
        "place_type_id": "restaurant",
    },
    "attractions": {
        "label": "ATTRACTIONS",
        "urls": [TRIPADVISOR_ATTRACTIONS_URL],
        "detail_marker": "/Attraction_Review-",
        "id_field": "attraction_id",
        "place_type_id": "historical_site",
    },
}


def paginated_url(url: str, page_number: int) -> str:
    if page_number <= 1:
        return url
    offset = (page_number - 1) * TRIPADVISOR_RESULTS_PER_PAGE
    if "FindRestaurants" in url:
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}offset={offset}"
    return re.sub(r"(-g\d+)-", rf"\1-oa{offset}-", url, count=1)


def normalize_url(url: Any) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    return urljoin("https://www.tripadvisor.com", url.strip())


def place_id_from_url(url: Any) -> str | None:
    match = re.search(r"-d(\d+)-", str(url or ""))
    return match.group(1) if match else None


def place_name_from_url(url: Any) -> str | None:
    match = re.search(r"Reviews(?:-or\d+)?-([^-]+(?:-[^-]+)*)-", str(url or ""))
    if not match:
        return None
    return clean_text(match.group(1).replace("_", " ").replace("-", " "))


def tripadvisor_catalog_rating(value: Any) -> float | None:
    rating = parse_float(value)
    if rating is None:
        return None
    return rating if 0 <= rating <= 5 else None


def tripadvisor_catalog_review_count(value: Any) -> int | None:
    text = str(value or "")
    if not re.search(r"\breviews?\b", text, flags=re.IGNORECASE):
        return None
    return parse_number(text)


def normalize_place_card(raw: dict[str, Any], kind: str) -> dict[str, Any] | None:
    config = PLACE_CONFIGS[kind]
    url = normalize_url(raw.get("url"))
    if not url:
        return None
    name = clean_text(raw.get("name")) or place_name_from_url(url)
    if not name:
        return None
    name = re.sub(r"^\d+\.\s*", "", name).strip()
    if re.search(r"\bbubbles?\b|reviews?|show prices|view deal", name, flags=re.IGNORECASE):
        return None

    text = clean_text(raw.get("text")) or ""
    price, currency = parse_price(text)
    review_score = first_nonempty(
        tripadvisor_catalog_rating(raw.get("rating")),
        tripadvisor_catalog_rating(text),
    )
    review_count = first_nonempty(
        raw.get("review_count"),
        tripadvisor_catalog_review_count(text),
    )
    source_place_id = valid_tripadvisor_location_id(
        raw.get("location_id")
    ) or place_id_from_url(url)
    if not source_place_id:
        print(
            f"[TRIPADVISOR][{config['label']}] "
            f"Skipping {name}: missing numeric locationId"
        )
        return None
    place = {
        "source": TRIPADVISOR_SOURCE_ID,
        config["id_field"]: source_place_id,
        "tripadvisor_id": source_place_id,
        "location_id": source_place_id,
        "source_place_id": source_place_id,
        "place_type_id": config["place_type_id"],
        "name": name,
        "property_url": url,
        "source_url": url,
        "address": clean_text(raw.get("address")),
        "city": "Zanzibar",
        "country_code": "TZ",
        "latitude": raw.get("latitude"),
        "longitude": raw.get("longitude"),
        "display_location": clean_text(raw.get("location")),
        "review_score": review_score,
        "review_count": review_count,
        "description": clean_text(raw.get("description")),
        "description_summary": clean_text(raw.get("description")),
        "photo_url": normalize_url(raw.get("image")),
        "photos": [url for url in [normalize_url(raw.get("image"))] if url],
        "gallery_photo_urls": [url for url in [normalize_url(raw.get("image"))] if url],
        "features": clean_text(raw.get("amenities")),
        "category_labels": config["label"].title(),
        "activity_type": config["label"].title(),
        "price": price,
        "currency": currency,
        "available": True,
        "booking_required": None,
        "guided_tour": None,
        "family_friendly": None,
        "raw": raw,
        "catalog_parse_method": raw.get("parse_method") or "graphql",
    }
    place["place_id"] = f"{TRIPADVISOR_SOURCE_ID}:{kind}:place:{source_place_id}"
    place["place_source_id"] = f"{TRIPADVISOR_SOURCE_ID}:{kind}:listing:{source_place_id}"
    return place


async def extract_place_cards(page: Page, detail_marker: str) -> list[dict[str, Any]]:
    return await page.evaluate(
        """
        ({detailMarker}) => {
            const text = (node) => (node?.innerText || node?.textContent || '').trim();
            const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
            const looksLikeName = (value) => {
                const text = clean(value).replace(/^\\d+\\.\\s*/, '');
                if (text.length < 3 || text.length > 140) return false;
                if (!/[A-Za-z]/.test(text)) return false;
                if (/\\bbubbles?\\b|reviews?|availability|view deal|show prices|sponsored|ad\\s/i.test(text)) return false;
                if (/^\\d+(\\.\\d+)?(?:\\s+\\d+(\\.\\d+)?)?/.test(text)) return false;
                if (/(US\\$|USD|TZS|\\$|€|£)\\s*\\d/i.test(text)) return false;
                return true;
            };
            const absolute = (href) => {
                try { return new URL(href, location.origin).href; }
                catch (_) { return null; }
            };
            const nameFromUrl = (url) => {
                const match = String(url || '').match(/Reviews(?:-or\\d+)?-([^-]+(?:-[^-]+)*)-/);
                if (!match) return '';
                return match[1].replace(/_/g, ' ').replace(/-/g, ' ').trim();
            };
            const usefulAncestor = (anchor) => {
                let node = anchor;
                for (let depth = 0; node && depth < 8; depth += 1, node = node.parentElement) {
                    const value = text(node);
                    if (value.length >= 50 && value.length <= 7000) return node;
                }
                return anchor.closest('article, section, div') || anchor;
            };
            const marker = String(detailMarker || '').replace(/^\\//, '');
            const anchors = [...document.querySelectorAll(`a[href*="${marker}"]`)];
            const byUrl = new Map();
            for (const anchor of anchors) {
                const url = absolute(anchor.getAttribute('href'));
                if (!url) continue;
                const root = usefulAncestor(anchor);
                const rootText = text(root);
                const lines = rootText.split('\\n').map((line) => clean(line)).filter(Boolean);
                const headingName = text(root.querySelector('h1, h2, h3'));
                const anchorName = looksLikeName(text(anchor)) ? clean(text(anchor)).replace(/^\\d+\\.\\s*/, '') : '';
                const lineName = lines.map((line) => line.replace(/^\\d+\\.\\s*/, '')).find(looksLikeName) || '';
                const name = (looksLikeName(headingName) ? headingName.replace(/^\\d+\\.\\s*/, '') : '') ||
                    anchorName ||
                    lineName ||
                    nameFromUrl(url);
                const image = root.querySelector('img')?.currentSrc ||
                    root.querySelector('img')?.src ||
                    root.querySelector('img')?.getAttribute('data-lazyurl') ||
                    root.querySelector('img')?.getAttribute('data-src');
                const ratingLabel = root.querySelector('[aria-label*="bubble"], [aria-label*="rating"]')?.getAttribute('aria-label') || '';
                const reviewText = lines.find((line) => /review/i.test(line) && /\\d/.test(line)) || '';
                const priceText = lines.find((line) => /(US\\$|USD|TZS|\\$|€|£)\\s*\\d/i.test(line)) || '';
                byUrl.set(url, {name, url, image, text: rootText, rating: ratingLabel, review_count: reviewText, price: priceText});
            }
            return [...byUrl.values()].filter((card) => looksLikeName(card.name));
        }
        """,
        {"detailMarker": detail_marker},
    )


async def enrich_tripadvisor_places(
    context: BrowserContext,
    places: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not places:
        return places
    page = await context.new_page()
    enriched = []
    try:
        for index, place in enumerate(places, start=1):
            print(f"[TRIPADVISOR] Detail {index}/{len(places)}: {place.get('name')}")
            try:
                await page.goto(place["property_url"], wait_until="domcontentloaded", timeout=120_000)
                await accept_cookies(page)
                await page.wait_for_timeout(1800)
                data = await page.evaluate(
                    """
                    () => {
                        const text = (node) => (node?.innerText || node?.textContent || '').trim();
                        const unique = (items) => [...new Set(items.map((item) => (item || '').trim()).filter(Boolean))];
                        const title = text(document.querySelector('h1')) || (document.title || '').replace(/ - Tripadvisor.*$/i, '').trim();
                        const description = document.querySelector('meta[name="description"]')?.content || '';
                        const address = text(document.querySelector('[itemprop="address"], address, [data-test-target*="address"]'));
                        const bodyText = document.body?.innerText || '';
                        const scripts = [...document.scripts].map((script) => script.textContent || '').join('\\n');
                        const images = unique([...document.images].map((img) => img.currentSrc || img.src || img.getAttribute('data-lazyurl') || img.getAttribute('data-src')).filter((src) => src && /^https?:/.test(src))).slice(0, 20);
                        return {title, description, address, bodyText, scripts, images};
                    }
                    """
                )
            except Exception as error:
                print(f"[TRIPADVISOR] Detail failed for {place.get('name')}: {error}")
                enriched.append(place)
                continue
            combined = f"{data.get('scripts') or ''}\n{data.get('bodyText') or ''}" if isinstance(data, dict) else ""
            lat_match = re.search(r'"lat(?:itude)?"\s*:\s*"?(-?\d+(?:\.\d+)?)"?', combined)
            lon_match = re.search(r'"(?:lng|longitude)"\s*:\s*"?(-?\d+(?:\.\d+)?)"?', combined)
            images = data.get("images") if isinstance(data, dict) and isinstance(data.get("images"), list) else []
            enriched.append(
                {
                    **place,
                    "name": clean_text(data.get("title")) or place.get("name"),
                    "address": clean_text(data.get("address")) or place.get("address"),
                    "description": clean_text(data.get("description")) or place.get("description"),
                    "description_summary": clean_text(data.get("description")) or place.get("description_summary"),
                    "photo_url": place.get("photo_url") or (images[0] if images else None),
                    "photos": images or place.get("photos") or [],
                    "gallery_photo_urls": images or place.get("gallery_photo_urls") or [],
                    "latitude": parse_float(lat_match.group(1)) if lat_match else place.get("latitude"),
                    "longitude": parse_float(lon_match.group(1)) if lon_match else place.get("longitude"),
                }
            )
    finally:
        await page.close()
    return enriched


async def scrape_tripadvisor_places_in_context(
    context: BrowserContext,
    kind: str,
) -> list[dict[str, Any]]:
    config = PLACE_CONFIGS[kind]
    page = context.pages[0] if context.pages else await context.new_page()
    all_places: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_location_ids: set[str] = set()
    print_category_header("Tripadvisor", config["label"].title())
    pagination_confirmed = tripadvisor_pagination_confirmed(kind)
    for base_url in config["urls"]:
        for page_number in tripadvisor_place_page_numbers():
            url = paginated_url(base_url, page_number)
            raw_cards = []
            graphql_result: TripadvisorGraphQLResult | None = None
            offset = (page_number - 1) * TRIPADVISOR_RESULTS_PER_PAGE
            if kind == "attractions" and TRIPADVISOR_ATTRACTIONS_GRAPHQL_ENABLED:
                graphql_result = await fetch_tripadvisor_attractions_graphql_result(
                    page,
                    page_number,
                )
            elif kind == "restaurants" and TRIPADVISOR_RESTAURANTS_GRAPHQL_ENABLED:
                graphql_result = await fetch_tripadvisor_restaurants_graphql_result(
                    page,
                    page_number,
                )

            if graphql_result is not None:
                if graphql_result.blocked or graphql_result.failed:
                    print(f"[TRIPADVISOR][{config['label']}] Collection stopped by GraphQL failure")
                    break
                raw_cards = graphql_result.cards
                if graphql_result.raw_count == 0 or not raw_cards:
                    print_catalog_page(
                        page_number,
                        graphql_result.raw_count,
                        0,
                        len(all_places),
                        offset=offset,
                    )
                    if not pagination_confirmed:
                        print(
                            f"[TRIPADVISOR][{config['label']}] "
                            "Stopped after pagination diagnostics."
                        )
                    else:
                        print(f"[TRIPADVISOR][{config['label']}] Collection complete")
                    break
            else:
                print(f"[TRIPADVISOR] {config['label']} page {page_number}: {url}")
                try:
                    await page.goto(url, wait_until="load", timeout=120_000)
                    await wait_for_tripadvisor_content(
                        page,
                        f'a[href*="{config["detail_marker"].lstrip("/")}"]',
                        f"{config['label'].lower()} page {page_number}",
                    )
                    raw_cards = await extract_place_cards(page, config["detail_marker"])
                    if raw_cards:
                        print(
                            f"[TRIPADVISOR] Browser page found "
                            f"{len(raw_cards)} {kind} links."
                        )
                    else:
                        html_text = await fetch_static_html(page, url)
                        raw_cards = extract_static_cards_from_html(
                            html_text,
                            config["detail_marker"].lstrip("/"),
                        )
                        if raw_cards:
                            print(
                                f"[TRIPADVISOR] Static HTML fallback found "
                                f"{len(raw_cards)} {kind} links."
                            )
                except Exception as error:
                    print(f"[TRIPADVISOR] {config['label']} page {page_number} failed: {error}")
                    break

            page_places = []
            rejected_cards = 0
            for raw_card in raw_cards:
                try:
                    place = normalize_place_card(raw_card, kind)
                    if not place:
                        rejected_cards += 1
                        continue
                    if place["property_url"] in seen_urls:
                        continue
                    location_id = str(place.get("tripadvisor_id") or "").strip()
                    if location_id and location_id in seen_location_ids:
                        continue
                    if location_id:
                        seen_location_ids.add(location_id)
                    seen_urls.add(place["property_url"])
                    page_places.append(place)
                except Exception as error:
                    print(f"[TRIPADVISOR] Failed to parse one {kind} place: {error}")
                    rejected_cards += 1
            if graphql_result is not None:
                if (
                    kind == "attractions"
                    and page_number == 1
                    and graphql_result.metadata.get("totalResults") is not None
                ):
                    print(f"API-reported total results: {graphql_result.metadata.get('totalResults')}")
                print_catalog_page(
                    page_number,
                    graphql_result.raw_count,
                    len(page_places),
                    len(all_places) + len(page_places),
                    offset=None if not pagination_confirmed else offset,
                )
                if rejected_cards:
                    print(
                        f"[TRIPADVISOR][{config['label']}] "
                        f"Rejected incomplete cards={rejected_cards}"
                    )
            else:
                print(f"[TRIPADVISOR] Found {len(page_places)} {kind} on page {page_number}")
            if not page_places:
                if graphql_result is not None:
                    if not pagination_confirmed:
                        print(
                            f"[TRIPADVISOR][{config['label']}] "
                            "Stopped after pagination diagnostics."
                        )
                    else:
                        print(f"[TRIPADVISOR][{config['label']}] Collection complete")
                break
            all_places.extend(page_places)
            if not pagination_confirmed:
                break
            if graphql_result is not None and place_metadata_complete(
                graphql_result.metadata,
                (page_number - 1) * TRIPADVISOR_RESULTS_PER_PAGE,
                graphql_result.raw_count,
            ):
                print(f"[TRIPADVISOR][{config['label']}] Collection complete")
                break
            await page.wait_for_timeout(1200)
        if kind in {"attractions", "restaurants"}:
            break
    if kind == "attractions" and not TRIPADVISOR_ATTRACTION_PAGINATION_CONFIRMED:
        print("WARNING Attraction pagination not confirmed.")
        print(f"Attractions currently extracted: {len(all_places)}")
        total_results = None
        debug_path = ATTRACTION_PAGINATION_DEBUG_DIR / "page_1.json"
        if debug_path.exists():
            try:
                debug_data = json.loads(debug_path.read_text(encoding="utf-8"))
                total_results = debug_data.get("api_reported_total_results")
            except (OSError, json.JSONDecodeError):
                total_results = None
        if total_results is not None:
            print(f"API-reported total results: {total_results}")
        print()
        print("=" * 60)
        print("WARNING TRIPADVISOR ATTRACTIONS INCOMPLETE")
        print(f"Attractions currently extracted : {len(all_places)}")
        print(f"API-reported total results       : {total_results}")
        print("Pagination                       : NOT CONFIRMED")
        print("=" * 60)
        return []
    if kind == "restaurants" and not TRIPADVISOR_RESTAURANT_PAGINATION_CONFIRMED:
        print("WARNING Restaurant pagination not confirmed.")
        print(f"Restaurants currently extracted: {len(all_places)}")
        print()
        print("=" * 60)
        print("WARNING TRIPADVISOR RESTAURANTS INCOMPLETE")
        print(f"Restaurants currently extracted : {len(all_places)}")
        print("Pagination                       : NOT CONFIRMED")
        print("=" * 60)
        return all_places
    else:
        print_catalog_complete(config["label"].title(), len(all_places))
    if kind in {"attractions", "restaurants"}:
        return all_places
    return await enrich_tripadvisor_places(context, all_places)
