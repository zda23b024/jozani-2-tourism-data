import asyncio
import argparse

from config.configuration import BOOKING_BROWSER_PROFILE_DIR, LOG_DIR, ensure_project_dirs
from database.create_tables import (
    fetch_existing_review_ids_by_place_source_ids,
    fetch_existing_review_state_by_hotel,
    fetch_known_booking_places_for_reviews,
    save_to_postgres,
)
from normalizers.table_builder import build_all_tables
from scraper.booking.scrape_attractions import (
    attraction_place_source_id,
    attraction_source_place_id,
    scrape_attractions_in_context,
    scrape_reviews_for_attractions,
)
from scraper.booking.scrape_reviews import scrape_reviews_for_hotels
from scraper.booking.scrape_stays import scrape_hotels_in_context
from utils.browser_helpers import close_context, launch_context
from utils.file_manager import save_all_table_outputs
from utils.run_logging import RunLogger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Booking.com tourism data.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--all",
        action="store_true",
        help="Build/refresh the full catalog and collect reviews, without saving date-based availability.",
    )
    mode.add_argument(
        "--daily",
        action="store_true",
        help="Collect today's date-based prices/availability and new reviews. This is the default.",
    )
    mode.add_argument(
        "--reviews",
        action="store_true",
        help="Load known places from PostgreSQL and collect only new reviews.",
    )
    mode.add_argument(
        "--catalog",
        action="store_true",
        help="Refresh hotel and attraction details without reviews or date-based availability.",
    )
    parser.add_argument(
        "--only",
        choices=["all", "hotels", "attractions"],
        default="all",
        help="Limit catalog/daily scraping to hotels, attractions, or both.",
    )
    return parser.parse_args()


def selected_mode(args: argparse.Namespace) -> str:
    if args.all:
        return "all"
    if args.reviews:
        return "reviews"
    if args.catalog:
        return "catalog"
    return "daily"


def reviewable_attraction_place_source_ids(attractions: list[dict]) -> list[str]:
    return [
        attraction_place_source_id(attraction_source_place_id(attraction))
        for attraction in attractions
    ]


async def collect_reviews(
    booking_context,
    hotels: list[dict],
    attractions: list[dict],
    incremental: bool = True,
) -> list[dict]:
    reviews = []

    if hotels:
        existing_review_state = (
            fetch_existing_review_state_by_hotel(hotels) if incremental else {}
        )
        reviews = await scrape_reviews_for_hotels(
            booking_context,
            hotels,
            existing_review_state,
        )

    if attractions:
        existing_attraction_review_ids = (
            fetch_existing_review_ids_by_place_source_ids(
                reviewable_attraction_place_source_ids(attractions)
            )
            if incremental
            else {}
        )
        reviews.extend(
            await scrape_reviews_for_attractions(
                booking_context,
                attractions,
                existing_attraction_review_ids,
            )
        )

    return reviews


async def main(mode: str = "daily", only: str = "all") -> None:
    ensure_project_dirs()
    hotels = []
    reviews = []
    attractions = []
    include_reviews = mode in {"all", "daily", "reviews"}
    include_availability = mode == "daily"

    if mode == "reviews":
        hotels, attractions = fetch_known_booking_places_for_reviews()
        if only == "hotels":
            attractions = []
        elif only == "attractions":
            hotels = []
        if not hotels and not attractions:
            print("No saved Booking.com hotels or attractions were found for review scraping.")
            return

    booking_context = await launch_context(
        BOOKING_BROWSER_PROFILE_DIR,
        "Booking.com",
    )
    try:
        if mode != "reviews":
            if only in {"all", "hotels"}:
                hotels = await scrape_hotels_in_context(
                    booking_context,
                    catalog_mode=mode in {"all", "catalog"},
                )

            if only in {"all", "attractions"}:
                attractions = await scrape_attractions_in_context(
                    booking_context,
                    catalog_mode=mode in {"all", "catalog"},
                )

        if include_reviews:
            reviews = await collect_reviews(
                booking_context,
                hotels,
                attractions,
                incremental=mode != "all",
            )
    finally:
        await close_context(booking_context)

    if not hotels and not attractions:
        print("No hotels or attractions were collected.")
        return

    tables = build_all_tables(
        hotels,
        reviews,
        attractions,
        include_availability=include_availability,
        run_type=f"booking_{mode}",
    )
    tables = save_all_table_outputs(tables)
    save_to_postgres(tables)


if __name__ == "__main__":
    ensure_project_dirs()
    args = parse_args()
    with RunLogger(LOG_DIR) as log_path:
        asyncio.run(main(selected_mode(args), args.only))
        print(f"Completed run. Log saved to: {log_path}")
