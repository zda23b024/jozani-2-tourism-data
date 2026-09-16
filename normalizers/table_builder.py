import hashlib
import json
from typing import Any

import pandas as pd

from config.configuration import (
    ADULTS,
    CHECKIN,
    CHECKOUT,
    CHILDREN,
    ROOMS,
    SEARCH_LOCATION_ID,
    SEARCH_TERM,
)
from database.models import (
    DEFAULT_LOCATIONS,
    DEFAULT_PLACE_TYPES,
    DEFAULT_SOURCES,
    TABLE_COLUMNS,
)
from utils.helpers import first_nonempty, limited_rows, safe_filename, stable_review_id

BOOKING_SOURCE_ID = "booking"
TRIPADVISOR_SOURCE_ID = "tripadvisor"
DEFAULT_LOCATION_ID = SEARCH_LOCATION_ID


def utc_now() -> str:
    return pd.Timestamp.utcnow().isoformat()


def stable_id(*parts: Any, prefix: str | None = None) -> str:
    source = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}" if prefix else digest


def split_semicolon_values(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = str(value).split(";")
    cleaned = []
    for raw_value in raw_values:
        text = str(raw_value or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def detect_place_type_id(item: dict) -> str:
    name = str(item.get("name") or "").lower()
    accommodation_type = str(item.get("accommodation_type_id") or "").lower()

    if "resort" in name:
        return "resort"
    if "villa" in name:
        return "villa"
    if "guest" in name:
        return "guest_house"
    if "apartment" in name or accommodation_type in {"201", "219", "220"}:
        return "apartment"
    return "hotel"


def item_source_id(item: dict) -> str:
    source = str(item.get("source") or BOOKING_SOURCE_ID).strip().lower()
    return source or BOOKING_SOURCE_ID


def hotel_source_place_id(item: dict) -> str:
    source = item_source_id(item)
    if source == TRIPADVISOR_SOURCE_ID:
        value = item.get("tripadvisor_id")
    else:
        value = item.get("hotel_id")
    if value not in (None, ""):
        return str(value)
    return safe_filename(
        f"{source}_{item.get('name')}_{item.get('latitude')}_{item.get('longitude')}"
    )


def hotel_place_id(item: dict) -> str:
    return f"{item_source_id(item)}:place:{hotel_source_place_id(item)}"


def hotel_place_source_id(item: dict) -> str:
    return f"{item_source_id(item)}:listing:{hotel_source_place_id(item)}"


def booking_source_place_id(item: dict) -> str:
    return hotel_source_place_id(item)


def place_id_from_source(source_place_id: str) -> str:
    return f"booking:place:{source_place_id}"


def place_source_id_from_source(source_place_id: str) -> str:
    return f"booking:listing:{source_place_id}"


def place_id_for_source(source_id: str, source_place_id: str) -> str:
    return f"{source_id}:place:{source_place_id}"


def place_source_id_for_source(source_id: str, source_place_id: str) -> str:
    return f"{source_id}:listing:{source_place_id}"


def attraction_source_place_id(item: dict) -> str:
    value = first_nonempty(
        item.get("source_place_id"),
        item.get("attraction_id"),
        item.get("tripadvisor_id") if item_source_id(item) == TRIPADVISOR_SOURCE_ID else None,
    )
    if value not in (None, ""):
        return str(value)
    return safe_filename(
        f"{item.get('name')}_{item.get('latitude')}_{item.get('longitude')}"
    )


def attraction_place_id(source_place_id: str) -> str:
    return f"booking:attraction:place:{source_place_id}"


def attraction_place_source_id(source_place_id: str) -> str:
    return f"booking:attraction:listing:{source_place_id}"


def generic_place_id(item: dict, default_kind: str = "place") -> str:
    explicit = item.get("place_id")
    if explicit:
        return str(explicit)
    source_id = item_source_id(item)
    source_place_id = attraction_source_place_id(item)
    if source_id == BOOKING_SOURCE_ID:
        return attraction_place_id(source_place_id)
    return f"{source_id}:{default_kind}:place:{source_place_id}"


def generic_place_source_id(item: dict, default_kind: str = "listing") -> str:
    explicit = item.get("place_source_id")
    if explicit:
        return str(explicit)
    source_id = item_source_id(item)
    source_place_id = attraction_source_place_id(item)
    if source_id == BOOKING_SOURCE_ID:
        return attraction_place_source_id(source_place_id)
    return f"{source_id}:{default_kind}:listing:{source_place_id}"


def is_hotel_like_item(item: dict) -> bool:
    return item.get("hotel_id") not in (None, "") or item.get("place_type_id") in {
        "hotel",
        "resort",
        "villa",
        "guest_house",
        "apartment",
    }


def source_place_id_for_item(item: dict) -> str:
    if is_hotel_like_item(item):
        return hotel_source_place_id(item)
    return attraction_source_place_id(item)


def place_id_for_item(item: dict, default_kind: str = "attraction") -> str:
    if is_hotel_like_item(item):
        return hotel_place_id(item)
    return generic_place_id(item, default_kind)


def place_source_id_for_item(item: dict, default_kind: str = "attraction") -> str:
    if is_hotel_like_item(item):
        return hotel_place_source_id(item)
    return generic_place_source_id(item, default_kind)


def image_hash(image_url: str) -> str:
    return hashlib.sha256(image_url.encode("utf-8")).hexdigest()


def clean_image_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value


def numeric_or_none(value: Any) -> Any:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def int_or_none(value: Any) -> int | None:
    numeric = numeric_or_none(value)
    if numeric is None:
        return None
    return int(numeric)


def build_master_rows(now: str) -> dict[str, list[dict]]:
    def with_timestamps(rows: list[dict]) -> list[dict]:
        return [
            {
                **row,
                "is_active": row.get("is_active", True),
                "created_at": row.get("created_at") or now,
                "updated_at": row.get("updated_at") or now,
            }
            for row in rows
        ]

    return {
        "sources": with_timestamps(DEFAULT_SOURCES),
        "place_types": with_timestamps(DEFAULT_PLACE_TYPES),
        "locations": with_timestamps(DEFAULT_LOCATIONS),
    }


def build_scraping_run(now: str, hotels: list[dict], reviews: list[dict], attractions: list[dict]) -> dict:
    places_count = len(hotels) + len(attractions)
    run_source_ids = {item_source_id(hotel) for hotel in hotels}
    run_source_ids.update(item_source_id(attraction) for attraction in attractions)
    run_source_ids.update(
        str(review.get("source") or BOOKING_SOURCE_ID).lower()
        for review in reviews
        if review.get("source")
    )
    if len(run_source_ids) == 1:
        source_id = next(iter(run_source_ids))
    elif not run_source_ids:
        source_id = BOOKING_SOURCE_ID
    else:
        source_id = BOOKING_SOURCE_ID if BOOKING_SOURCE_ID in run_source_ids else sorted(run_source_ids)[0]
    scraping_run_id = (
        f"{source_id}:{safe_filename(SEARCH_TERM)}:"
        f"{CHECKIN}:{CHECKOUT}:{safe_filename(now)}"
    )
    return {
        "scraping_run_id": scraping_run_id,
        "source_id": source_id,
        "run_type": "booking_collection",
        "entity_type": "mixed" if hotels and attractions else ("places" if places_count else "reviews"),
        "status": "completed",
        "started_at": now,
        "completed_at": now,
        "places_found": places_count,
        "places_inserted": places_count,
        "places_updated": 0,
        "reviews_found": len(reviews),
        "reviews_inserted": len(reviews),
        "reviews_skipped": 0,
        "records_found": places_count + len(reviews),
        "records_new": places_count + len(reviews),
        "records_updated": 0,
        "pages_total": None,
        "pages_successful": None,
        "pages_failed": None,
        "stop_reason": None,
        "error_count": 0,
        "error_message": None,
        "log_file": None,
        "created_at": now,
    }


def normalize_places(hotels: list[dict], now: str) -> list[dict]:
    rows = []
    for hotel in hotels:
        rows.append(
            {
                "place_id": hotel_place_id(hotel),
                "place_type_id": detect_place_type_id(hotel),
                "location_id": DEFAULT_LOCATION_ID,
                "canonical_name": hotel.get("name"),
                "short_description": first_nonempty(
                    hotel.get("description_summary"),
                    hotel.get("description"),
                ),
                "latitude": hotel.get("latitude"),
                "longitude": hotel.get("longitude"),
                "address": hotel.get("address"),
                "phone": hotel.get("phone"),
                "email": hotel.get("email"),
                "website": hotel.get("website"),
                "is_active": True,
                "status": "active",
                "is_verified": False,
                "average_rating": hotel.get("review_score"),
                "total_reviews": hotel.get("review_count"),
                "sentiment_score": None,
                "first_seen_at": now,
                "last_seen_at": now,
                "created_at": now,
                "updated_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["places"])


def attraction_place_type_id(item: dict) -> str:
    text = " ".join(
        str(item.get(key) or "").lower()
        for key in ["activity_type", "activity_type_slug", "category_labels", "tag_labels", "name"]
    )
    if "boat" in text or "cruise" in text:
        return "boat_tour"
    if "water" in text or "snorkel" in text or "diving" in text or "swim" in text:
        return "water_activity"
    if "museum" in text:
        return "museum"
    if "market" in text:
        return "market"
    if "park" in text or "forest" in text:
        return "national_park" if "park" in text else "forest"
    if "histor" in text:
        return "historical_site"
    if "beach" in text:
        return "beach"
    return "boat_tour" if "tour" in text else "historical_site"


def normalize_attraction_places(attractions: list[dict], now: str) -> list[dict]:
    rows = []
    for attraction in attractions:
        rows.append(
            {
                "place_id": generic_place_id(attraction, "attraction"),
                "place_type_id": attraction.get("place_type_id") or attraction_place_type_id(attraction),
                "location_id": DEFAULT_LOCATION_ID,
                "canonical_name": attraction.get("name"),
                "short_description": first_nonempty(
                    attraction.get("description_summary"),
                    attraction.get("description"),
                ),
                "latitude": attraction.get("latitude"),
                "longitude": attraction.get("longitude"),
                "address": attraction.get("address"),
                "phone": attraction.get("phone"),
                "email": attraction.get("email"),
                "website": attraction.get("website"),
                "is_active": attraction.get("available") is not False,
                "status": "active" if attraction.get("available") is not False else "inactive",
                "is_verified": False,
                "average_rating": attraction.get("review_score"),
                "total_reviews": attraction.get("review_count"),
                "sentiment_score": None,
                "first_seen_at": now,
                "last_seen_at": now,
                "created_at": now,
                "updated_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["places"])


def normalize_place_source_records(hotels: list[dict], now: str) -> list[dict]:
    rows = []
    for hotel in hotels:
        source_id = item_source_id(hotel)
        source_place_id = hotel_source_place_id(hotel)
        rows.append(
            {
                "place_source_id": place_source_id_for_source(source_id, source_place_id),
                "place_id": place_id_for_source(source_id, source_place_id),
                "source_id": source_id,
                "source_place_id": source_place_id,
                "source_name": hotel.get("name"),
                "source_url": hotel.get("property_url"),
                "source_category": str(hotel.get("accommodation_type_id") or ""),
                "latitude": hotel.get("latitude"),
                "longitude": hotel.get("longitude"),
                "star_rating": hotel.get("star_rating"),
                "review_score": hotel.get("review_score"),
                "review_count": hotel.get("review_count"),
                "ranking_position": hotel.get("ranking_position"),
                "ranking_total": hotel.get("ranking_total"),
                "ranking_text": hotel.get("ranking_text"),
                "ranking_category": hotel.get("ranking_category"),
                "popularity_score": hotel.get("popularity_score"),
                "is_active": True,
                "first_scraped_at": now,
                "matching_confidence": 1.0,
                "last_scraped_at": now,
                "raw_json": hotel,
                "created_at": now,
                "updated_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["place_source_records"])


def normalize_attraction_source_records(attractions: list[dict], now: str) -> list[dict]:
    rows = []
    for attraction in attractions:
        source_id = item_source_id(attraction)
        source_place_id = attraction_source_place_id(attraction)
        rows.append(
            {
                "place_source_id": generic_place_source_id(attraction, "attraction"),
                "place_id": generic_place_id(attraction, "attraction"),
                "source_id": source_id,
                "source_place_id": source_place_id,
                "source_name": attraction.get("name"),
                "source_url": attraction.get("property_url"),
                "source_category": first_nonempty(
                    attraction.get("activity_type"),
                    attraction.get("category_labels"),
                ),
                "latitude": attraction.get("latitude"),
                "longitude": attraction.get("longitude"),
                "star_rating": attraction.get("star_rating"),
                "review_score": attraction.get("review_score"),
                "review_count": attraction.get("review_count"),
                "ranking_position": attraction.get("ranking_position"),
                "ranking_total": attraction.get("ranking_total"),
                "ranking_text": attraction.get("ranking_text"),
                "ranking_category": attraction.get("ranking_category"),
                "popularity_score": attraction.get("popularity_score"),
                "is_active": attraction.get("available") is not False,
                "first_scraped_at": now,
                "matching_confidence": 1.0,
                "last_scraped_at": now,
                "raw_json": attraction.get("raw") or attraction,
                "created_at": now,
                "updated_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["place_source_records"])


def normalize_accommodations(hotels: list[dict], now: str) -> list[dict]:
    rows = []
    for hotel in hotels:
        rows.append(
            {
                "place_id": hotel_place_id(hotel),
                "place_source_id": hotel_place_source_id(hotel),
                "star_rating": hotel.get("star_rating"),
                "checkin_from": hotel.get("checkin_from") or hotel.get("checkin_time"),
                "checkin_until": hotel.get("checkin_until"),
                "checkout_from": hotel.get("checkout_from"),
                "checkout_until": hotel.get("checkout_until") or hotel.get("checkout_time"),
                "checkin_time": hotel.get("checkin_time"),
                "checkout_time": hotel.get("checkout_time"),
                "pets_allowed": hotel.get("pets_free"),
                "children_allowed": bool(hotel.get("child_policy")) if hotel.get("child_policy") else None,
                "child_friendly": bool(hotel.get("child_policy")),
                "beachfront": bool(hotel.get("beach_distance") in (None, "")),
                "distance_to_beach_m": int_or_none(hotel.get("distance_to_beach_m")),
                "distance_to_beach": first_nonempty(
                    hotel.get("beach_distance"),
                    hotel.get("beach_walking_time"),
                ),
                "license_number": None,
                "airport_shuttle": hotel.get("airport_shuttle"),
                "parking_available": hotel.get("parking_available"),
                "breakfast_available": bool(hotel.get("meal_plan")) if hotel.get("meal_plan") else None,
                "breakfast_type": hotel.get("meal_plan"),
                "property_class": hotel.get("property_class"),
                "chain_name": hotel.get("chain_name"),
                "year_opened": int_or_none(hotel.get("year_opened")),
                "year_renovated": int_or_none(hotel.get("year_renovated")),
                "raw_json": hotel.get("raw") or hotel,
                "created_at": now,
                "updated_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["accommodations"])


def normalize_attractions(attractions: list[dict], now: str) -> list[dict]:
    rows = []
    for attraction in attractions:
        if attraction.get("place_type_id") == "restaurant":
            continue
        rows.append(
            {
                "place_id": generic_place_id(attraction, "attraction"),
                "place_source_id": generic_place_source_id(attraction, "attraction"),
                "attraction_category": first_nonempty(
                    attraction.get("activity_type"),
                    attraction.get("category_labels"),
                ),
                "attraction_subcategory": attraction.get("tag_labels"),
                "attraction_type": first_nonempty(
                    attraction.get("activity_type"),
                    attraction.get("category_labels"),
                ),
                "recommended_duration": attraction.get("recommended_duration"),
                "duration_minutes": int_or_none(attraction.get("duration_minutes")),
                "ticket_required": attraction.get("ticket_required"),
                "booking_available": attraction.get("booking_available"),
                "price_from": numeric_or_none(attraction.get("price")),
                "entry_fee": numeric_or_none(attraction.get("price")),
                "currency_code": attraction.get("currency"),
                "currency": attraction.get("currency"),
                "booking_required": attraction.get("booking_required"),
                "guided_tour": attraction.get("guided_tour"),
                "family_friendly": attraction.get("family_friendly"),
                "accessibility_info": attraction.get("accessibility_info"),
                "best_visit_time": attraction.get("best_visit_time"),
                "historical_significance": attraction.get("description"),
                "natural_significance": attraction.get("features"),
                "raw_json": attraction.get("raw") or attraction,
                "created_at": now,
                "updated_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["attractions"])


def normalize_restaurants(attractions: list[dict], now: str) -> list[dict]:
    rows = []
    for restaurant in attractions:
        if restaurant.get("place_type_id") != "restaurant":
            continue
        rows.append(
            {
                "place_id": generic_place_id(restaurant, "attraction"),
                "place_source_id": generic_place_source_id(restaurant, "attraction"),
                "price_range": first_nonempty(
                    restaurant.get("price_range"),
                    restaurant.get("price"),
                ),
                "restaurant_type": first_nonempty(
                    restaurant.get("restaurant_type"),
                    restaurant.get("category_labels"),
                ),
                "price_level": restaurant.get("price_level"),
                "reservation_available": restaurant.get("reservation_available"),
                "delivery_available": restaurant.get("delivery_available"),
                "takeaway_available": restaurant.get("takeaway_available"),
                "takeaway": restaurant.get("takeaway_available"),
                "delivery": restaurant.get("delivery_available"),
                "seating_available": restaurant.get("seating_available"),
                "outdoor_seating": restaurant.get("outdoor_seating"),
                "halal": restaurant.get("halal"),
                "vegetarian": restaurant.get("vegetarian"),
                "vegan": restaurant.get("vegan"),
                "raw_json": restaurant.get("raw") or restaurant,
                "created_at": now,
                "updated_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["restaurants"])


def normalize_activities(attractions: list[dict], now: str) -> list[dict]:
    rows = []
    for attraction in attractions:
        text = " ".join(
            str(attraction.get(key) or "").lower()
            for key in ["activity_type", "activity_type_slug", "category_labels", "tag_labels", "name"]
        )
        if not any(word in text for word in ["tour", "activity", "boat", "water", "cruise", "snorkel", "diving"]):
            continue
        source_place_id = attraction_source_place_id(attraction)
        rows.append(
            {
                "place_id": generic_place_id(attraction, "attraction"),
                "activity_type": attraction.get("activity_type"),
                "duration_minutes": int_or_none(attraction.get("duration_minutes")),
                "minimum_age": None,
                "starting_price": numeric_or_none(attraction.get("price")),
                "currency": attraction.get("currency"),
                "guide_included": attraction.get("guided_tour"),
                "equipment_included": None,
                "pickup_available": bool(
                    "pickup" in str(attraction.get("features") or "").lower()
                    or "pickup" in str(attraction.get("badges") or "").lower()
                ),
                "created_at": now,
                "updated_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["activities"])


def normalize_amenities_and_links(
    hotels: list[dict],
    now: str,
) -> tuple[list[dict], list[dict]]:
    amenity_by_name: dict[str, dict] = {}
    place_amenities: list[dict] = []

    for hotel in hotels:
        source_id = item_source_id(hotel)
        place_id = hotel_place_id(hotel)
        amenity_values = []
        amenity_values.extend(split_semicolon_values(hotel.get("property_usp_facilities")))
        amenity_values.extend(split_semicolon_values(hotel.get("full_facilities")))
        amenity_values.extend(split_semicolon_values(hotel.get("property_badges")))
        amenity_values.extend(split_semicolon_values(hotel.get("sustainability_certifications")))

        if hotel.get("free_cancellation") is True:
            amenity_values.append("Free cancellation")
        if hotel.get("no_prepayment") is True:
            amenity_values.append("No prepayment")
        if hotel.get("pets_free") is True:
            amenity_values.append("Pets allowed for free")
        if hotel.get("meal_plan"):
            amenity_values.append(str(hotel.get("meal_plan")))

        for amenity_name in dict.fromkeys(amenity_values):
            amenity_id = f"amenity:{safe_filename(amenity_name)}"
            amenity_by_name[amenity_id] = {
                "amenity_id": amenity_id,
                "amenity_name": amenity_name,
                "amenity_category": f"{source_id.title()} property feature",
                "created_at": now,
                "updated_at": now,
            }
            place_amenities.append(
                {
                    "place_id": place_id,
                    "place_source_id": hotel_place_source_id(hotel),
                    "amenity_id": amenity_id,
                    "is_available": True,
                    "additional_info": None,
                    "created_at": now,
                }
            )

    return (
        limited_rows(list(amenity_by_name.values()), TABLE_COLUMNS["amenities"]),
        limited_rows(place_amenities, TABLE_COLUMNS["place_amenities"]),
    )


def normalize_attraction_amenities_and_links(
    attractions: list[dict],
    now: str,
) -> tuple[list[dict], list[dict]]:
    amenity_by_name: dict[str, dict] = {}
    place_amenities: list[dict] = []
    for attraction in attractions:
        source_id = item_source_id(attraction)
        place_id = generic_place_id(attraction, "attraction")
        values = []
        values.extend(split_semicolon_values(attraction.get("badges")))
        values.extend(split_semicolon_values(attraction.get("features")))
        values.extend(split_semicolon_values(attraction.get("category_labels")))
        values.extend(split_semicolon_values(attraction.get("tag_labels")))
        if attraction.get("free_cancellation") is True:
            values.append("Free cancellation")
        if attraction.get("guided_tour") is True:
            values.append("Guided tour")
        if attraction.get("family_friendly") is True:
            values.append("Family friendly")

        for amenity_name in dict.fromkeys(values):
            amenity_id = f"amenity:{safe_filename(amenity_name)}"
            amenity_by_name[amenity_id] = {
                "amenity_id": amenity_id,
                "amenity_name": amenity_name,
                "amenity_category": f"{source_id.title()} attraction feature",
                "created_at": now,
                "updated_at": now,
            }
            place_amenities.append(
                {
                    "place_id": place_id,
                    "place_source_id": generic_place_source_id(attraction, "attraction"),
                    "amenity_id": amenity_id,
                    "is_available": True,
                    "additional_info": None,
                    "created_at": now,
                }
            )

    return (
        limited_rows(list(amenity_by_name.values()), TABLE_COLUMNS["amenities"]),
        limited_rows(place_amenities, TABLE_COLUMNS["place_amenities"]),
    )


def normalize_images(hotels: list[dict], now: str) -> list[dict]:
    rows = []
    for hotel in hotels:
        source_id = item_source_id(hotel)
        photo_urls = []
        if hotel.get("photo_url"):
            photo_urls.append(hotel.get("photo_url"))
        photo_urls.extend(hotel.get("gallery_photo_urls") or [])
        for display_order, photo_url in enumerate(dict.fromkeys(photo_urls), start=1):
            photo_url = clean_image_url(photo_url)
            if not photo_url:
                continue
            photo_hash = image_hash(str(photo_url))
            rows.append(
                {
                    "image_id": f"{source_id}:image:{photo_hash}",
                    "place_id": hotel_place_id(hotel),
                    "place_source_id": hotel_place_source_id(hotel),
                    "source_id": source_id,
                    "source_image_id": photo_hash,
                    "image_url": photo_url,
                    "thumbnail_url": hotel.get("photo_url") if display_order == 1 else None,
                    "image_hash": photo_hash,
                    "image_type": "primary" if display_order == 1 else "gallery",
                    "caption": hotel.get("name"),
                    "display_order": display_order,
                    "is_primary": display_order == 1,
                    "width_pixels": None,
                    "height_pixels": None,
                    "raw_json": {"source_url": photo_url},
                    "created_at": now,
                }
            )
    return limited_rows(rows, TABLE_COLUMNS["images"])


def normalize_attraction_images(attractions: list[dict], now: str) -> list[dict]:
    rows = []
    for attraction in attractions:
        source_id = item_source_id(attraction)
        place_id = generic_place_id(attraction, "attraction")
        for display_order, photo_url in enumerate(attraction.get("photos") or [], start=1):
            photo_url = clean_image_url(photo_url)
            if not photo_url:
                continue
            photo_hash = image_hash(str(photo_url))
            rows.append(
                {
                    "image_id": f"{source_id}:attraction:image:{photo_hash}",
                    "place_id": place_id,
                    "place_source_id": generic_place_source_id(attraction, "attraction"),
                    "source_id": source_id,
                    "source_image_id": photo_hash,
                    "image_url": photo_url,
                    "thumbnail_url": None,
                    "image_hash": photo_hash,
                    "image_type": "primary" if display_order == 1 else "gallery",
                    "caption": attraction.get("name"),
                    "display_order": display_order,
                    "is_primary": display_order == 1,
                    "width_pixels": None,
                    "height_pixels": None,
                    "raw_json": {"source_url": photo_url},
                    "created_at": now,
                }
            )
    return limited_rows(rows, TABLE_COLUMNS["images"])


def reviewer_id_from_review(review: dict) -> str:
    source = str(review.get("source") or BOOKING_SOURCE_ID).lower()
    source_reviewer_id = first_nonempty(
        review.get("reviewer_id"),
        stable_id(
            source,
            review.get("reviewer_name"),
            review.get("reviewer_country"),
            prefix=f"{safe_filename(source)}:reviewer-key",
        ),
    )
    return f"{safe_filename(source)}:reviewer:{safe_filename(source_reviewer_id)}"


def normalize_reviewers(reviews: list[dict], now: str) -> list[dict]:
    rows_by_id = {}
    for review in reviews:
        source_id = str(review.get("source") or BOOKING_SOURCE_ID).lower()
        reviewer_id = reviewer_id_from_review(review)
        source_reviewer_id = first_nonempty(
            review.get("reviewer_id"),
            reviewer_id.split(":reviewer:", 1)[-1],
        )
        rows_by_id[reviewer_id] = {
            "reviewer_id": reviewer_id,
            "source_id": source_id,
            "source_reviewer_id": source_reviewer_id,
            "reviewer_name": review.get("reviewer_name"),
            "username": review.get("username"),
            "country_code": review.get("reviewer_country_code"),
            "country_name": review.get("reviewer_country"),
            "country": review.get("reviewer_country"),
            "profile_url": review.get("reviewer_profile_url"),
            "reviewer_level": review.get("reviewer_level"),
            "profile_image": review.get("reviewer_profile_url"),
            "profile_image_url": review.get("reviewer_profile_image_url"),
            "contribution_count": int_or_none(review.get("contribution_count")),
            "helpful_vote_count": int_or_none(review.get("reviewer_helpful_votes")),
            "raw_json": review.get("reviewer_raw_json"),
            "created_at": now,
            "updated_at": now,
        }
    return limited_rows(list(rows_by_id.values()), TABLE_COLUMNS["reviewers"])


def normalize_reviews(reviews: list[dict], places: list[dict], now: str) -> list[dict]:
    known_place_ids = {
        (item_source_id(place), source_place_id_for_item(place)): (
            place_id_for_item(place, "attraction"),
            place_source_id_for_item(place, "attraction"),
        )
        for place in places
    }
    rows = []
    for review in reviews:
        source_id = str(review.get("source") or BOOKING_SOURCE_ID).lower()
        explicit_place_id = review.get("place_id")
        explicit_place_source_id = review.get("place_source_id")
        source_place_id = str(review.get("source_place_id") or review.get("hotel_id") or "")

        if explicit_place_id and explicit_place_source_id:
            place_id = explicit_place_id
            place_source_id = explicit_place_source_id
        else:
            known_place = known_place_ids.get((source_id, source_place_id))
            if not known_place:
                continue
            place_id, place_source_id = known_place

        source_review_id = stable_review_id(review)
        rows.append(
            {
                "review_id": f"{safe_filename(source_id)}:review:{safe_filename(source_review_id)}",
                "place_id": place_id,
                "place_source_id": place_source_id,
                "reviewer_id": reviewer_id_from_review(review),
                "source_review_id": source_review_id,
                "review_title": review.get("review_title"),
                "review_text": review.get("review_text"),
                "positive_text": review.get("positive_text"),
                "negative_text": review.get("negative_text"),
                "review_score": review.get("review_score"),
                "rating_scale": review.get("rating_scale") or (5 if source_id == TRIPADVISOR_SOURCE_ID else 10),
                "language": review.get("language"),
                "language_code": review.get("language_code") or review.get("language"),
                "original_language_code": review.get("original_language_code"),
                "review_date": review.get("review_date"),
                "visit_date": review.get("stayed_date"),
                "stay_date": review.get("stay_date") or review.get("stayed_date"),
                "trip_type": review.get("trip_type"),
                "travel_type": review.get("travel_type"),
                "room_name": review.get("room_name"),
                "verified_stay": None,
                "is_verified": review.get("is_verified"),
                "is_machine_translated": review.get("is_machine_translated"),
                "helpful_votes": review.get("helpful_votes"),
                "source_url": review.get("source_url"),
                "sentiment": None,
                "emotion": None,
                "spam_score": None,
                "raw_json": review.get("raw_json"),
                "created_at": now,
                "updated_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["reviews"])


def normalize_review_category_scores(reviews: list[dict], now: str) -> list[dict]:
    rows = []
    seen: set[tuple[str, str]] = set()
    for review in reviews:
        source_id = str(review.get("source") or BOOKING_SOURCE_ID).lower()
        source_review_id = stable_review_id(review)
        review_id = f"{safe_filename(source_id)}:review:{safe_filename(source_review_id)}"
        for rating in review.get("additional_ratings") or []:
            if not isinstance(rating, dict):
                continue
            category_name = rating.get("category_name")
            score = numeric_or_none(rating.get("score"))
            if not category_name or score is None:
                continue
            key = (review_id, str(category_name))
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "id": stable_id(
                        review_id,
                        category_name,
                        prefix=f"{safe_filename(source_id)}:review-category",
                    ),
                    "review_id": review_id,
                    "category_name": category_name,
                    "score": score,
                    "rating_scale": rating.get("rating_scale") or review.get("rating_scale"),
                    "created_at": now,
                }
            )
    return limited_rows(rows, TABLE_COLUMNS["review_category_scores"])


def normalize_review_responses(reviews: list[dict], places: list[dict], now: str) -> list[dict]:
    known_source_ids = {
        (item_source_id(place), source_place_id_for_item(place))
        for place in places
    }
    rows = []
    for review in reviews:
        if not review.get("response_text"):
            continue
        source_id = str(review.get("source") or BOOKING_SOURCE_ID).lower()
        explicit_place_source_id = review.get("place_source_id")
        source_place_id = str(review.get("source_place_id") or review.get("hotel_id") or "")
        if explicit_place_source_id:
            pass
        elif (source_id, source_place_id) not in known_source_ids:
            continue
        source_review_id = stable_review_id(review)
        source_response_id = first_nonempty(
            review.get("response_id"),
            stable_id(
                source_review_id,
                review.get("response_text"),
                review.get("response_date"),
                prefix=f"{safe_filename(source_id)}:response-key",
            ),
        )
        rows.append(
            {
                "response_id": f"{safe_filename(source_id)}:response:{safe_filename(source_response_id)}",
                "review_id": f"{safe_filename(source_id)}:review:{safe_filename(source_review_id)}",
                "source_response_id": source_response_id,
                "responder_name": review.get("responder_name"),
                "responder_role": review.get("responder_role"),
                "response_text": review.get("response_text"),
                "response_date": review.get("response_date"),
                "raw_json": review.get("response_raw_json"),
                "created_at": now,
                "updated_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["review_responses"])


def normalize_availability_offers(
    hotels: list[dict],
    scraping_run_id: str,
    now: str,
) -> list[dict]:
    rows = []
    for hotel in hotels:
        source_id = item_source_id(hotel)
        source_place_id = hotel_source_place_id(hotel)
        price = numeric_or_none(hotel.get("price"))
        rows.append(
            {
                "offer_id": stable_id(
                    source_id,
                    source_place_id,
                    CHECKIN,
                    CHECKOUT,
                    now,
                    prefix=f"{source_id}:offer",
                ),
                "place_source_id": place_source_id_for_source(source_id, source_place_id),
                "scraping_run_id": scraping_run_id,
                "checkin": CHECKIN,
                "checkout": CHECKOUT,
                "adults": ADULTS,
                "children": CHILDREN,
                "rooms": ROOMS,
                "room_name": None,
                "available": not bool(hotel.get("sold_out")),
                "price": price,
                "currency": hotel.get("currency"),
                "price_per_night": price,
                "breakfast": bool(hotel.get("meal_plan")),
                "free_cancellation": hotel.get("free_cancellation"),
                "scraped_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["availability_offers"])


def normalize_attraction_availability_offers(
    attractions: list[dict],
    scraping_run_id: str,
    now: str,
) -> list[dict]:
    rows = []
    for attraction in attractions:
        if attraction.get("place_type_id") == "restaurant":
            continue
        source_id = item_source_id(attraction)
        source_place_id = attraction_source_place_id(attraction)
        price = numeric_or_none(attraction.get("price"))
        rows.append(
            {
                "offer_id": stable_id(
                    source_id,
                    "attraction",
                    source_place_id,
                    CHECKIN,
                    CHECKOUT,
                    now,
                    prefix=f"{source_id}:attraction:offer",
                ),
                "place_source_id": generic_place_source_id(attraction, "attraction"),
                "scraping_run_id": scraping_run_id,
                "checkin": CHECKIN,
                "checkout": CHECKOUT,
                "adults": ADULTS,
                "children": CHILDREN,
                "rooms": None,
                "room_name": None,
                "available": attraction.get("available"),
                "price": price,
                "currency": attraction.get("currency"),
                "price_per_night": None,
                "breakfast": None,
                "free_cancellation": attraction.get("free_cancellation"),
                "scraped_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["availability_offers"])


def normalize_attraction_policies(attractions: list[dict], now: str) -> list[dict]:
    rows = []
    for attraction in attractions:
        if attraction.get("place_type_id") == "restaurant":
            continue
        policy_text = attraction.get("cancellation_policy")
        if not policy_text:
            continue
        source_id = item_source_id(attraction)
        source_place_id = attraction_source_place_id(attraction)
        rows.append(
            {
                "policy_id": stable_id(
                    source_id,
                    "attraction",
                    source_place_id,
                    "cancellation",
                    policy_text,
                    prefix=f"{source_id}:attraction:policy",
                ),
                "place_id": generic_place_id(attraction, "attraction"),
                "place_source_id": generic_place_source_id(attraction, "attraction"),
                "policy_type": "cancellation",
                "policy_text": policy_text,
                "effective_from": CHECKIN,
                "effective_to": None,
                "created_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["place_policies"])


def normalize_hotel_policies(hotels: list[dict], now: str) -> list[dict]:
    rows = []
    policy_fields = [
        ("house_rules", "house_rules_text"),
        ("child", "child_policy"),
        ("pet", "pet_policy"),
        ("payment", "payment_policy"),
    ]
    for hotel in hotels:
        source_id = item_source_id(hotel)
        source_place_id = hotel_source_place_id(hotel)
        place_id = place_id_for_source(source_id, source_place_id)
        for policy_type, field_name in policy_fields:
            policy_text = hotel.get(field_name)
            if not policy_text:
                continue
            rows.append(
                {
                    "policy_id": stable_id(
                        source_id,
                        "hotel",
                        source_place_id,
                        policy_type,
                        policy_text,
                        prefix=f"{source_id}:hotel:policy",
                    ),
                    "place_id": place_id,
                    "place_source_id": place_source_id_for_source(source_id, source_place_id),
                    "policy_type": policy_type,
                    "policy_text": policy_text,
                    "effective_from": CHECKIN,
                    "effective_to": None,
                    "created_at": now,
                }
            )
    return limited_rows(rows, TABLE_COLUMNS["place_policies"])


def build_all_tables(
    hotels: list[dict],
    reviews: list[dict],
    attractions: list[dict] | None = None,
    include_availability: bool = True,
    run_type: str = "booking_collection",
) -> dict[str, list[dict]]:
    attractions = attractions or []
    now = utc_now()
    tables = {table_name: [] for table_name in TABLE_COLUMNS}
    tables.update(build_master_rows(now))

    scraping_run = build_scraping_run(now, hotels, reviews, attractions)
    scraping_run["run_type"] = run_type
    amenities, place_amenities = normalize_amenities_and_links(hotels, now)
    attraction_amenities, attraction_place_amenities = (
        normalize_attraction_amenities_and_links(attractions, now)
    )

    tables["places"] = normalize_places(hotels, now) + normalize_attraction_places(
        attractions,
        now,
    )
    tables["place_source_records"] = normalize_place_source_records(
        hotels,
        now,
    ) + normalize_attraction_source_records(attractions, now)
    tables["accommodations"] = normalize_accommodations(hotels, now)
    tables["attractions"] = normalize_attractions(attractions, now)
    tables["restaurants"] = normalize_restaurants(attractions, now)
    tables["amenities"] = amenities + attraction_amenities
    tables["place_amenities"] = place_amenities + attraction_place_amenities
    tables["images"] = normalize_images(hotels, now) + normalize_attraction_images(
        attractions,
        now,
    )
    tables["reviewers"] = normalize_reviewers(reviews, now)
    tables["reviews"] = normalize_reviews(reviews, hotels + attractions, now)
    tables["review_category_scores"] = normalize_review_category_scores(reviews, now)
    tables["review_responses"] = normalize_review_responses(reviews, hotels + attractions, now)
    tables["scraping_runs"] = [scraping_run]
    if include_availability:
        tables["availability_offers"] = normalize_availability_offers(
            hotels,
            scraping_run["scraping_run_id"],
            now,
        ) + normalize_attraction_availability_offers(
            attractions,
            scraping_run["scraping_run_id"],
            now,
        )
    tables["place_policies"] = normalize_hotel_policies(
        hotels,
        now,
    ) + normalize_attraction_policies(attractions, now)

    return tables
