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


def booking_source_place_id(item: dict) -> str:
    value = item.get("hotel_id")
    if value not in (None, ""):
        return str(value)
    return safe_filename(
        f"{item.get('name')}_{item.get('latitude')}_{item.get('longitude')}"
    )


def place_id_from_source(source_place_id: str) -> str:
    return f"booking:place:{source_place_id}"


def place_source_id_from_source(source_place_id: str) -> str:
    return f"booking:listing:{source_place_id}"


def attraction_source_place_id(item: dict) -> str:
    value = item.get("attraction_id")
    if value not in (None, ""):
        return str(value)
    return safe_filename(
        f"{item.get('name')}_{item.get('latitude')}_{item.get('longitude')}"
    )


def attraction_place_id(source_place_id: str) -> str:
    return f"booking:attraction:place:{source_place_id}"


def attraction_place_source_id(source_place_id: str) -> str:
    return f"booking:attraction:listing:{source_place_id}"


def image_hash(image_url: str) -> str:
    return hashlib.sha256(image_url.encode("utf-8")).hexdigest()


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
    scraping_run_id = (
        f"booking:{safe_filename(SEARCH_TERM)}:"
        f"{CHECKIN}:{CHECKOUT}:{safe_filename(now)}"
    )
    return {
        "scraping_run_id": scraping_run_id,
        "source_id": BOOKING_SOURCE_ID,
        "run_type": "booking_collection",
        "status": "completed",
        "started_at": now,
        "completed_at": now,
        "places_found": places_count,
        "places_inserted": places_count,
        "places_updated": 0,
        "reviews_found": len(reviews),
        "reviews_inserted": len(reviews),
        "reviews_skipped": 0,
        "error_count": 0,
        "error_message": None,
        "log_file": None,
        "created_at": now,
    }


def normalize_places(hotels: list[dict], now: str) -> list[dict]:
    rows = []
    for hotel in hotels:
        source_place_id = booking_source_place_id(hotel)
        rows.append(
            {
                "place_id": place_id_from_source(source_place_id),
                "place_type_id": detect_place_type_id(hotel),
                "location_id": DEFAULT_LOCATION_ID,
                "canonical_name": hotel.get("name"),
                "short_description": first_nonempty(
                    hotel.get("description_summary"),
                    hotel.get("description"),
                ),
                "latitude": hotel.get("latitude"),
                "longitude": hotel.get("longitude"),
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
        source_place_id = attraction_source_place_id(attraction)
        rows.append(
            {
                "place_id": attraction_place_id(source_place_id),
                "place_type_id": attraction_place_type_id(attraction),
                "location_id": DEFAULT_LOCATION_ID,
                "canonical_name": attraction.get("name"),
                "short_description": first_nonempty(
                    attraction.get("description_summary"),
                    attraction.get("description"),
                ),
                "latitude": attraction.get("latitude"),
                "longitude": attraction.get("longitude"),
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
        source_place_id = booking_source_place_id(hotel)
        rows.append(
            {
                "place_source_id": place_source_id_from_source(source_place_id),
                "place_id": place_id_from_source(source_place_id),
                "source_id": BOOKING_SOURCE_ID,
                "source_place_id": source_place_id,
                "source_name": hotel.get("name"),
                "source_url": hotel.get("property_url"),
                "source_category": str(hotel.get("accommodation_type_id") or ""),
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
        source_place_id = attraction_source_place_id(attraction)
        rows.append(
            {
                "place_source_id": attraction_place_source_id(source_place_id),
                "place_id": attraction_place_id(source_place_id),
                "source_id": BOOKING_SOURCE_ID,
                "source_place_id": source_place_id,
                "source_name": attraction.get("name"),
                "source_url": attraction.get("property_url"),
                "source_category": first_nonempty(
                    attraction.get("activity_type"),
                    attraction.get("category_labels"),
                ),
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
        source_place_id = booking_source_place_id(hotel)
        rows.append(
            {
                "place_id": place_id_from_source(source_place_id),
                "star_rating": hotel.get("star_rating"),
                "checkin_time": hotel.get("checkin_time"),
                "checkout_time": hotel.get("checkout_time"),
                "pets_allowed": hotel.get("pets_free"),
                "child_friendly": bool(hotel.get("child_policy")),
                "beachfront": bool(hotel.get("beach_distance") in (None, "")),
                "distance_to_beach": first_nonempty(
                    hotel.get("beach_distance"),
                    hotel.get("beach_walking_time"),
                ),
                "license_number": None,
                "created_at": now,
                "updated_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["accommodations"])


def normalize_attractions(attractions: list[dict], now: str) -> list[dict]:
    rows = []
    for attraction in attractions:
        source_place_id = attraction_source_place_id(attraction)
        rows.append(
            {
                "place_id": attraction_place_id(source_place_id),
                "attraction_type": first_nonempty(
                    attraction.get("activity_type"),
                    attraction.get("category_labels"),
                ),
                "entry_fee": numeric_or_none(attraction.get("price")),
                "currency": attraction.get("currency"),
                "booking_required": attraction.get("booking_required"),
                "guided_tour": attraction.get("guided_tour"),
                "family_friendly": attraction.get("family_friendly"),
                "best_visit_time": attraction.get("best_visit_time"),
                "historical_significance": attraction.get("description"),
                "natural_significance": attraction.get("features"),
                "created_at": now,
                "updated_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["attractions"])


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
                "place_id": attraction_place_id(source_place_id),
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
        source_place_id = booking_source_place_id(hotel)
        place_id = place_id_from_source(source_place_id)
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
                "amenity_category": "Booking.com property feature",
                "created_at": now,
                "updated_at": now,
            }
            place_amenities.append(
                {
                    "place_id": place_id,
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
        source_place_id = attraction_source_place_id(attraction)
        place_id = attraction_place_id(source_place_id)
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
                "amenity_category": "Booking.com attraction feature",
                "created_at": now,
                "updated_at": now,
            }
            place_amenities.append(
                {
                    "place_id": place_id,
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
        source_place_id = booking_source_place_id(hotel)
        photo_urls = []
        if hotel.get("photo_url"):
            photo_urls.append(hotel.get("photo_url"))
        photo_urls.extend(hotel.get("gallery_photo_urls") or [])
        for display_order, photo_url in enumerate(dict.fromkeys(photo_urls), start=1):
            if not photo_url:
                continue
            photo_hash = image_hash(str(photo_url))
            rows.append(
                {
                    "image_id": f"booking:image:{photo_hash}",
                    "place_id": place_id_from_source(source_place_id),
                    "source_id": BOOKING_SOURCE_ID,
                    "image_url": photo_url,
                    "image_hash": photo_hash,
                    "image_type": "primary" if display_order == 1 else "gallery",
                    "caption": hotel.get("name"),
                    "display_order": display_order,
                    "is_primary": display_order == 1,
                    "created_at": now,
                }
            )
    return limited_rows(rows, TABLE_COLUMNS["images"])


def normalize_attraction_images(attractions: list[dict], now: str) -> list[dict]:
    rows = []
    for attraction in attractions:
        source_place_id = attraction_source_place_id(attraction)
        place_id = attraction_place_id(source_place_id)
        for display_order, photo_url in enumerate(attraction.get("photos") or [], start=1):
            if not photo_url:
                continue
            photo_hash = image_hash(str(photo_url))
            rows.append(
                {
                    "image_id": f"booking:attraction:image:{photo_hash}",
                    "place_id": place_id,
                    "source_id": BOOKING_SOURCE_ID,
                    "image_url": photo_url,
                    "image_hash": photo_hash,
                    "image_type": "primary" if display_order == 1 else "gallery",
                    "caption": attraction.get("name"),
                    "display_order": display_order,
                    "is_primary": display_order == 1,
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
        source_reviewer_id = reviewer_id.split(":reviewer:", 1)[-1]
        rows_by_id[reviewer_id] = {
            "reviewer_id": reviewer_id,
            "source_id": source_id,
            "source_reviewer_id": source_reviewer_id,
            "reviewer_name": review.get("reviewer_name"),
            "country": review.get("reviewer_country"),
            "reviewer_level": None,
            "profile_image": None,
            "created_at": now,
            "updated_at": now,
        }
    return limited_rows(list(rows_by_id.values()), TABLE_COLUMNS["reviewers"])


def normalize_reviews(reviews: list[dict], hotels: list[dict], now: str) -> list[dict]:
    known_source_ids = {booking_source_place_id(hotel) for hotel in hotels}
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
            if source_place_id not in known_source_ids:
                continue
            place_id = place_id_from_source(source_place_id)
            place_source_id = place_source_id_from_source(source_place_id)

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
                "language": review.get("language"),
                "review_date": review.get("review_date"),
                "visit_date": review.get("stayed_date"),
                "room_name": review.get("room_name"),
                "verified_stay": None,
                "helpful_votes": None,
                "sentiment": None,
                "emotion": None,
                "spam_score": None,
                "created_at": now,
                "updated_at": now,
            }
        )
    return limited_rows(rows, TABLE_COLUMNS["reviews"])


def normalize_review_responses(reviews: list[dict], hotels: list[dict], now: str) -> list[dict]:
    known_source_ids = {booking_source_place_id(hotel) for hotel in hotels}
    rows = []
    for review in reviews:
        if not review.get("response_text"):
            continue
        source_id = str(review.get("source") or BOOKING_SOURCE_ID).lower()
        explicit_place_source_id = review.get("place_source_id")
        source_place_id = str(review.get("source_place_id") or review.get("hotel_id") or "")
        if explicit_place_source_id:
            pass
        elif source_place_id not in known_source_ids:
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
        source_place_id = booking_source_place_id(hotel)
        price = numeric_or_none(hotel.get("price"))
        rows.append(
            {
                "offer_id": stable_id(
                    BOOKING_SOURCE_ID,
                    source_place_id,
                    CHECKIN,
                    CHECKOUT,
                    now,
                    prefix="booking:offer",
                ),
                "place_source_id": place_source_id_from_source(source_place_id),
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
        source_place_id = attraction_source_place_id(attraction)
        price = numeric_or_none(attraction.get("price"))
        rows.append(
            {
                "offer_id": stable_id(
                    BOOKING_SOURCE_ID,
                    "attraction",
                    source_place_id,
                    CHECKIN,
                    CHECKOUT,
                    now,
                    prefix="booking:attraction:offer",
                ),
                "place_source_id": attraction_place_source_id(source_place_id),
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
        policy_text = attraction.get("cancellation_policy")
        if not policy_text:
            continue
        source_place_id = attraction_source_place_id(attraction)
        rows.append(
            {
                "policy_id": stable_id(
                    BOOKING_SOURCE_ID,
                    "attraction",
                    source_place_id,
                    "cancellation",
                    policy_text,
                    prefix="booking:attraction:policy",
                ),
                "place_id": attraction_place_id(source_place_id),
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
        source_place_id = booking_source_place_id(hotel)
        place_id = place_id_from_source(source_place_id)
        for policy_type, field_name in policy_fields:
            policy_text = hotel.get(field_name)
            if not policy_text:
                continue
            rows.append(
                {
                    "policy_id": stable_id(
                        BOOKING_SOURCE_ID,
                        "hotel",
                        source_place_id,
                        policy_type,
                        policy_text,
                        prefix="booking:hotel:policy",
                    ),
                    "place_id": place_id,
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
) -> dict[str, list[dict]]:
    attractions = attractions or []
    now = utc_now()
    tables = {table_name: [] for table_name in TABLE_COLUMNS}
    tables.update(build_master_rows(now))

    scraping_run = build_scraping_run(now, hotels, reviews, attractions)
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
    tables["amenities"] = amenities + attraction_amenities
    tables["place_amenities"] = place_amenities + attraction_place_amenities
    tables["images"] = normalize_images(hotels, now) + normalize_attraction_images(
        attractions,
        now,
    )
    tables["reviewers"] = normalize_reviewers(reviews, now)
    tables["reviews"] = normalize_reviews(reviews, hotels, now)
    tables["review_responses"] = normalize_review_responses(reviews, hotels, now)
    tables["scraping_runs"] = [scraping_run]
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
