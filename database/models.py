from config.configuration import (
    SEARCH_COUNTRY,
    SEARCH_ISLAND,
    SEARCH_LOCATION_ID,
    SEARCH_REGION,
    SEARCH_TERM,
)


SOURCE_COLUMNS = [
    "source_id",
    "source_name",
    "source_code",
    "base_url",
    "source_type",
    "is_active",
    "created_at",
    "updated_at",
]

PLACE_TYPE_COLUMNS = [
    "place_type_id",
    "type_name",
    "type_group",
    "description",
    "is_active",
    "created_at",
    "updated_at",
]

LOCATION_COLUMNS = [
    "location_id",
    "parent_location_id",
    "location_name",
    "location_type",
    "country",
    "region",
    "district",
    "island",
    "created_at",
    "updated_at",
]

PLACE_COLUMNS = [
    "place_id",
    "place_type_id",
    "location_id",
    "canonical_name",
    "short_description",
    "latitude",
    "longitude",
    "status",
    "is_verified",
    "average_rating",
    "total_reviews",
    "sentiment_score",
    "first_seen_at",
    "last_seen_at",
    "created_at",
    "updated_at",
]

PLACE_SOURCE_RECORD_COLUMNS = [
    "place_source_id",
    "place_id",
    "source_id",
    "source_place_id",
    "source_name",
    "source_url",
    "source_category",
    "matching_confidence",
    "last_scraped_at",
    "raw_json",
    "created_at",
    "updated_at",
]

ACCOMMODATION_COLUMNS = [
    "place_id",
    "star_rating",
    "checkin_time",
    "checkout_time",
    "pets_allowed",
    "child_friendly",
    "beachfront",
    "distance_to_beach",
    "license_number",
    "created_at",
    "updated_at",
]

RESTAURANT_COLUMNS = [
    "place_id",
    "restaurant_type",
    "price_level",
    "reservation_available",
    "takeaway",
    "delivery",
    "halal",
    "vegetarian",
    "vegan",
    "created_at",
    "updated_at",
]

ATTRACTION_COLUMNS = [
    "place_id",
    "attraction_type",
    "entry_fee",
    "currency",
    "booking_required",
    "guided_tour",
    "family_friendly",
    "best_visit_time",
    "historical_significance",
    "natural_significance",
    "created_at",
    "updated_at",
]

ACTIVITY_COLUMNS = [
    "place_id",
    "activity_type",
    "duration_minutes",
    "minimum_age",
    "starting_price",
    "currency",
    "guide_included",
    "equipment_included",
    "pickup_available",
    "created_at",
    "updated_at",
]

AMENITY_COLUMNS = [
    "amenity_id",
    "amenity_name",
    "amenity_category",
    "created_at",
    "updated_at",
]

PLACE_AMENITY_COLUMNS = [
    "place_id",
    "amenity_id",
    "is_available",
    "additional_info",
    "created_at",
]

IMAGE_COLUMNS = [
    "image_id",
    "place_id",
    "source_id",
    "image_url",
    "image_hash",
    "image_type",
    "caption",
    "display_order",
    "is_primary",
    "created_at",
]

REVIEWER_COLUMNS = [
    "reviewer_id",
    "source_id",
    "source_reviewer_id",
    "reviewer_name",
    "country",
    "reviewer_level",
    "profile_image",
    "created_at",
    "updated_at",
]

REVIEW_COLUMNS = [
    "review_id",
    "place_id",
    "place_source_id",
    "reviewer_id",
    "source_review_id",
    "review_title",
    "review_text",
    "positive_text",
    "negative_text",
    "review_score",
    "language",
    "review_date",
    "visit_date",
    "room_name",
    "verified_stay",
    "helpful_votes",
    "sentiment",
    "emotion",
    "spam_score",
    "raw_json",
    "created_at",
    "updated_at",
]

REVIEW_RESPONSE_COLUMNS = [
    "response_id",
    "review_id",
    "source_response_id",
    "responder_name",
    "responder_role",
    "response_text",
    "response_date",
    "raw_json",
    "created_at",
    "updated_at",
]

SCRAPING_RUN_COLUMNS = [
    "scraping_run_id",
    "source_id",
    "run_type",
    "status",
    "started_at",
    "completed_at",
    "places_found",
    "places_inserted",
    "places_updated",
    "reviews_found",
    "reviews_inserted",
    "reviews_skipped",
    "error_count",
    "error_message",
    "log_file",
    "created_at",
]

AVAILABILITY_OFFER_COLUMNS = [
    "offer_id",
    "place_source_id",
    "scraping_run_id",
    "checkin",
    "checkout",
    "adults",
    "children",
    "rooms",
    "room_name",
    "available",
    "price",
    "currency",
    "price_per_night",
    "breakfast",
    "free_cancellation",
    "scraped_at",
]

PLACE_POLICY_COLUMNS = [
    "policy_id",
    "place_id",
    "policy_type",
    "policy_text",
    "effective_from",
    "effective_to",
    "created_at",
]

TABLE_COLUMNS = {
    "sources": SOURCE_COLUMNS,
    "place_types": PLACE_TYPE_COLUMNS,
    "locations": LOCATION_COLUMNS,
    "places": PLACE_COLUMNS,
    "place_source_records": PLACE_SOURCE_RECORD_COLUMNS,
    "accommodations": ACCOMMODATION_COLUMNS,
    "attractions": ATTRACTION_COLUMNS,
    "amenities": AMENITY_COLUMNS,
    "place_amenities": PLACE_AMENITY_COLUMNS,
    "images": IMAGE_COLUMNS,
    "reviewers": REVIEWER_COLUMNS,
    "reviews": REVIEW_COLUMNS,
    "review_responses": REVIEW_RESPONSE_COLUMNS,
    "scraping_runs": SCRAPING_RUN_COLUMNS,
    "availability_offers": AVAILABILITY_OFFER_COLUMNS,
    "place_policies": PLACE_POLICY_COLUMNS,
}

TABLE_CONFLICT_COLUMNS = {
    "sources": ["source_id"],
    "place_types": ["place_type_id"],
    "locations": ["location_id"],
    "places": ["place_id"],
    "place_source_records": ["place_source_id"],
    "accommodations": ["place_id"],
    "attractions": ["place_id"],
    "amenities": ["amenity_id"],
    "place_amenities": ["place_id", "amenity_id"],
    "images": ["image_id"],
    "reviewers": ["reviewer_id"],
    "reviews": ["place_source_id", "source_review_id"],
    "review_responses": ["response_id"],
    "scraping_runs": ["scraping_run_id"],
    "availability_offers": ["offer_id"],
    "place_policies": ["policy_id"],
}

DEFAULT_SOURCES = [
    {
        "source_id": "booking",
        "source_name": "Booking.com",
        "source_code": "BOOKING",
        "base_url": "https://www.booking.com",
        "source_type": "Accommodation platform",
        "is_active": True,
    }
]

DEFAULT_PLACE_TYPES = [
    {"place_type_id": "hotel", "type_name": "Hotel", "type_group": "Accommodation"},
    {"place_type_id": "resort", "type_name": "Resort", "type_group": "Accommodation"},
    {"place_type_id": "villa", "type_name": "Villa", "type_group": "Accommodation"},
    {"place_type_id": "apartment", "type_name": "Apartment", "type_group": "Accommodation"},
    {"place_type_id": "guest_house", "type_name": "Guest House", "type_group": "Accommodation"},
    {"place_type_id": "restaurant", "type_name": "Restaurant", "type_group": "Restaurant"},
    {"place_type_id": "cafe", "type_name": "Cafe", "type_group": "Restaurant"},
    {"place_type_id": "beach", "type_name": "Beach", "type_group": "Attraction"},
    {"place_type_id": "forest", "type_name": "Forest", "type_group": "Attraction"},
    {"place_type_id": "museum", "type_name": "Museum", "type_group": "Attraction"},
    {"place_type_id": "historical_site", "type_name": "Historical Site", "type_group": "Attraction"},
    {"place_type_id": "national_park", "type_name": "National Park", "type_group": "Attraction"},
    {"place_type_id": "market", "type_name": "Market", "type_group": "Attraction"},
    {"place_type_id": "boat_tour", "type_name": "Boat Tour", "type_group": "Activity"},
    {"place_type_id": "water_activity", "type_name": "Water Activity", "type_group": "Activity"},
]

DEFAULT_LOCATIONS = [
    {
        "location_id": SEARCH_COUNTRY.lower().replace(" ", "_"),
        "parent_location_id": None,
        "location_name": SEARCH_COUNTRY,
        "location_type": "country",
        "country": SEARCH_COUNTRY,
    },
    {
        "location_id": SEARCH_REGION.lower().replace(" ", "_"),
        "parent_location_id": SEARCH_COUNTRY.lower().replace(" ", "_"),
        "location_name": SEARCH_REGION,
        "location_type": "region",
        "country": SEARCH_COUNTRY,
        "region": SEARCH_REGION,
    },
    {
        "location_id": SEARCH_ISLAND.lower().replace(" ", "_"),
        "parent_location_id": SEARCH_REGION.lower().replace(" ", "_"),
        "location_name": SEARCH_ISLAND,
        "location_type": "island",
        "country": SEARCH_COUNTRY,
        "region": SEARCH_REGION,
        "island": SEARCH_ISLAND,
    },
    {
        "location_id": SEARCH_LOCATION_ID,
        "parent_location_id": SEARCH_ISLAND.lower().replace(" ", "_"),
        "location_name": SEARCH_TERM,
        "location_type": "town",
        "country": SEARCH_COUNTRY,
        "region": SEARCH_REGION,
        "island": SEARCH_ISLAND,
    },
]
