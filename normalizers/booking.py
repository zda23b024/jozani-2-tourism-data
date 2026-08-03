from typing import Any

from normalizers.common import empty_table_bundle
from normalizers.table_builder import (
    normalize_accommodations,
    normalize_amenities_and_links,
    normalize_attraction_amenities_and_links,
    normalize_attraction_availability_offers,
    normalize_attraction_images,
    normalize_attraction_places,
    normalize_attraction_policies,
    normalize_attraction_source_records,
    normalize_attractions,
    normalize_availability_offers,
    normalize_hotel_policies,
    normalize_images,
    normalize_place_source_records,
    normalize_places,
)


def normalize_booking_data(
    hotels: list[dict[str, Any]] | None = None,
    attractions: list[dict[str, Any]] | None = None,
    scraping_run_id: str | None = None,
    now: str | None = None,
) -> dict[str, list[dict]]:
    """Convert Booking.com stays and attractions into database table rows."""
    hotels = hotels or []
    attractions = attractions or []
    if now is None:
        raise ValueError("now is required for Booking.com normalization")
    if scraping_run_id is None:
        raise ValueError("scraping_run_id is required for Booking.com normalization")

    hotel_amenities, hotel_place_amenities = normalize_amenities_and_links(hotels, now)
    attraction_amenities, attraction_place_amenities = (
        normalize_attraction_amenities_and_links(attractions, now)
    )

    tables = empty_table_bundle()
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
    tables["amenities"] = hotel_amenities + attraction_amenities
    tables["place_amenities"] = hotel_place_amenities + attraction_place_amenities
    tables["images"] = normalize_images(hotels, now) + normalize_attraction_images(
        attractions,
        now,
    )
    tables["availability_offers"] = normalize_availability_offers(
        hotels,
        scraping_run_id,
        now,
    ) + normalize_attraction_availability_offers(attractions, scraping_run_id, now)
    tables["place_policies"] = normalize_hotel_policies(
        hotels,
        now,
    ) + normalize_attraction_policies(attractions, now)
    return tables
