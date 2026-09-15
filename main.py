import asyncio
import argparse

from config.configuration import (
    BOOKING_BROWSER_PROFILE_DIR,
    BOOKING_ATTRACTION_REVIEW_PLACE_LIMIT,
    LOG_DIR,
    TRIPADVISOR_BROWSER_PROFILE_DIR,
    ensure_project_dirs,
)
from database.create_tables import (
    fetch_existing_review_ids_by_place_source_ids,
    fetch_existing_review_state_by_hotel,
    fetch_known_booking_places_for_reviews,
    fetch_known_tripadvisor_places_for_reviews,
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
from scraper.tripadvisor.scrape_places import scrape_tripadvisor_places_in_context
from scraper.tripadvisor.scrape_places import (
    TRIPADVISOR_ATTRACTION_PAGINATION_CONFIRMED,
    TRIPADVISOR_RESTAURANT_PAGINATION_CONFIRMED,
)
from scraper.tripadvisor.scrape_reviews import scrape_reviews_for_tripadvisor_places
from scraper.tripadvisor.scrape_stays import scrape_tripadvisor_hotels_in_context
from utils.browser_helpers import close_context, launch_context
from utils.console_output import (
    print_category_summary,
    print_overall_summary,
    print_platform_summary,
)
from utils.file_manager import save_all_table_outputs
from utils.helpers import safe_filename
from utils.run_logging import RunLogger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect tourism data from supported providers.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--all",
        action="store_true",
        help="Build/refresh the full catalog and collect reviews, without saving date-based availability.",
    )
    mode.add_argument(
        "--daily",
        action="store_true",
        help="Collect today's date-based prices/availability and new reviews.",
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
        choices=["all", "hotels", "attractions", "restaurants"],
        default="all",
        help=(
            "Limit scraping to hotels, attractions, restaurants, or all. "
            "Without a mode, attractions/restaurants run catalog-only."
        ),
    )
    parser.add_argument(
        "--source",
        choices=["booking", "tripadvisor", "both"],
        default="both",
        help="Choose which provider to scrape. Defaults to both.",
    )
    return parser.parse_args()


def selected_mode(args: argparse.Namespace) -> str:
    if args.all:
        return "all"
    if args.reviews:
        return "reviews"
    if args.catalog:
        return "catalog"
    if args.only in {"attractions", "restaurants"}:
        return "catalog"
    return "daily"


def is_tripadvisor_restaurant(place: dict) -> bool:
    return (
        place.get("restaurant_id") is not None
        or str(place.get("place_type_id") or "").lower() == "restaurant"
    )


def is_tripadvisor_attraction(place: dict) -> bool:
    return not is_tripadvisor_restaurant(place)


def reviews_for_places(reviews: list[dict], places: list[dict]) -> int:
    place_source_ids: set[str] = set()
    for place in places:
        place_source_id = place.get("place_source_id")
        if place_source_id:
            place_source_ids.add(str(place_source_id))
            continue
        if str(place.get("source") or "").lower() == "booking" and place.get("attraction_id"):
            place_source_ids.add(attraction_place_source_id(attraction_source_place_id(place)))
    return sum(
        1
        for review in reviews
        if str(review.get("place_source_id") or "") in place_source_ids
    )


def reviewable_attraction_place_source_ids(attractions: list[dict]) -> list[str]:
    return [
        attraction_place_source_id(attraction_source_place_id(attraction))
        for attraction in attractions
    ]


def booking_attraction_review_places_processed(attractions: list[dict]) -> int:
    reviewable_attractions = [
        attraction
        for attraction in attractions
        if attraction.get("property_url")
    ]
    if BOOKING_ATTRACTION_REVIEW_PLACE_LIMIT is not None:
        reviewable_attractions = reviewable_attractions[:BOOKING_ATTRACTION_REVIEW_PLACE_LIMIT]
    return len(reviewable_attractions)


def print_booking_attraction_review_summary(
    attractions_processed: int,
    reviews_collected: int,
) -> None:
    print()
    print("=" * 60)
    print("BOOKING.COM ATTRACTION REVIEWS COMPLETE")
    print(f"Attractions processed: {attractions_processed}")
    print(f"Reviews collected: {reviews_collected}")
    print("=" * 60)


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


def should_run_booking(source: str) -> bool:
    return source in {"booking", "both"}


def should_run_tripadvisor(source: str) -> bool:
    return source in {"tripadvisor", "both"}


def hotel_duplicate_key(hotel: dict) -> str:
    name = safe_filename(hotel.get("name"))
    latitude = hotel.get("latitude")
    longitude = hotel.get("longitude")
    if latitude not in (None, "") and longitude not in (None, ""):
        try:
            return f"{name}:geo:{round(float(latitude), 4)}:{round(float(longitude), 4)}"
        except (TypeError, ValueError):
            pass
    location = safe_filename(
        hotel.get("address")
        or hotel.get("display_location")
        or hotel.get("city")
    )
    return f"{name}:loc:{location}"


def combine_hotels_without_obvious_duplicates(
    primary_hotels: list[dict],
    secondary_hotels: list[dict],
) -> list[dict]:
    combined = list(primary_hotels)
    seen_keys = {hotel_duplicate_key(hotel) for hotel in combined}
    for hotel in secondary_hotels:
        key = hotel_duplicate_key(hotel)
        if key in seen_keys:
            print(
                "[BOTH] Skipping obvious duplicate hotel from "
                f"{hotel.get('source')}: {hotel.get('name')}"
            )
            continue
        seen_keys.add(key)
        combined.append(hotel)
    return combined


async def scrape_booking_data(mode: str, only: str) -> tuple[list[dict], list[dict], list[dict]]:
    hotels = []
    reviews = []
    attractions = []
    include_reviews = mode in {"all", "daily", "reviews"}

    if mode == "reviews":
        hotels, attractions = fetch_known_booking_places_for_reviews()
        if only == "hotels":
            attractions = []
        elif only in {"attractions", "restaurants"}:
            hotels = []
        if not hotels and not attractions:
            print("No saved Booking.com hotels or attractions were found for review scraping.")
            return hotels, reviews, attractions

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

    return hotels, reviews, attractions


async def scrape_tripadvisor_data(mode: str, only: str) -> tuple[list[dict], list[dict], list[dict]]:
    reviews: list[dict] = []
    attractions: list[dict] = []
    include_reviews = mode in {"all", "daily", "reviews"}
    hotels: list[dict] = []

    if mode == "reviews":
        hotels, attractions = fetch_known_tripadvisor_places_for_reviews()
        if only == "hotels":
            attractions = []
        elif only in {"attractions", "restaurants"}:
            hotels = []
            if only == "restaurants":
                attractions = [
                    place
                    for place in attractions
                    if is_tripadvisor_restaurant(place)
                ]
            else:
                attractions = [
                    place
                    for place in attractions
                    if is_tripadvisor_attraction(place)
                ]
        if not hotels and not attractions:
            print("No saved Tripadvisor hotels or attractions were found for review scraping.")
            return hotels, reviews, attractions

    tripadvisor_context = await launch_context(
        TRIPADVISOR_BROWSER_PROFILE_DIR,
        "Tripadvisor",
    )
    try:
        if mode != "reviews" and only in {"all", "hotels"}:
            hotels = await scrape_tripadvisor_hotels_in_context(tripadvisor_context)
        if mode != "reviews" and only in {"all", "attractions"}:
            attractions.extend(
                await scrape_tripadvisor_places_in_context(
                    tripadvisor_context,
                    "attractions",
                )
            )
        if mode != "reviews" and only in {"all", "restaurants"}:
            attractions.extend(
                await scrape_tripadvisor_places_in_context(
                    tripadvisor_context,
                    "restaurants",
                )
            )
        tripadvisor_places = hotels + attractions
        if include_reviews and tripadvisor_places:
            reviews = await scrape_reviews_for_tripadvisor_places(
                tripadvisor_context,
                tripadvisor_places,
            )
    finally:
        await close_context(tripadvisor_context)
    return hotels, reviews, attractions


async def main(mode: str = "daily", only: str = "all", source: str = "both") -> None:
    ensure_project_dirs()
    hotels = []
    reviews = []
    attractions = []
    include_availability = mode == "daily"

    if should_run_booking(source):
        booking_hotels, booking_reviews, booking_attractions = await scrape_booking_data(
            mode,
            only,
        )
        if only in {"all", "hotels"}:
            print_category_summary(
                "Booking.com",
                "Hotels",
                len(booking_hotels),
                reviews_for_places(booking_reviews, booking_hotels)
                if mode != "catalog"
                else None,
            )
        if mode == "reviews" and only == "attractions":
            print_booking_attraction_review_summary(
                booking_attraction_review_places_processed(booking_attractions),
                len(booking_reviews),
            )
        elif only in {"all", "attractions"}:
            print_category_summary(
                "Booking.com",
                "Attractions",
                len(booking_attractions),
                reviews_for_places(booking_reviews, booking_attractions)
                if mode != "catalog"
                else None,
            )
        print_platform_summary(
            "Booking.com",
            hotels=len(booking_hotels),
            attractions=len(booking_attractions),
            restaurants=None,
            reviews=len(booking_reviews),
        )
        hotels = combine_hotels_without_obvious_duplicates(hotels, booking_hotels)
        reviews.extend(booking_reviews)
        attractions.extend(booking_attractions)

    if should_run_tripadvisor(source):
        tripadvisor_hotels, tripadvisor_reviews, tripadvisor_attractions = (
            await scrape_tripadvisor_data(mode, only)
        )
        if (
            mode == "catalog"
            and source == "tripadvisor"
            and only == "attractions"
            and not TRIPADVISOR_ATTRACTION_PAGINATION_CONFIRMED
        ):
            return
        tripadvisor_restaurants = [
            place
            for place in tripadvisor_attractions
            if is_tripadvisor_restaurant(place)
        ]
        tripadvisor_non_restaurant_attractions = [
            place
            for place in tripadvisor_attractions
            if is_tripadvisor_attraction(place)
        ]
        if only in {"all", "hotels"}:
            print_category_summary(
                "Tripadvisor",
                "Hotels",
                len(tripadvisor_hotels),
                reviews_for_places(tripadvisor_reviews, tripadvisor_hotels)
                if mode != "catalog"
                else None,
            )
        if only in {"all", "attractions"}:
            if TRIPADVISOR_ATTRACTION_PAGINATION_CONFIRMED:
                print_category_summary(
                    "Tripadvisor",
                    "Attractions",
                    len(tripadvisor_non_restaurant_attractions),
                    reviews_for_places(
                        tripadvisor_reviews,
                        tripadvisor_non_restaurant_attractions,
                    )
                    if mode != "catalog"
                    else None,
                )
            else:
                print()
                print("=" * 60)
                print("WARNING TRIPADVISOR ATTRACTIONS PAGINATION NOT CONFIRMED")
                print(
                    "Attractions currently collected: "
                    f"{len(tripadvisor_non_restaurant_attractions)}"
                )
                if mode != "catalog":
                    print(
                        "Reviews collected: "
                        f"{reviews_for_places(tripadvisor_reviews, tripadvisor_non_restaurant_attractions)}"
                    )
                print("=" * 60)
        if only in {"all", "restaurants"}:
            if TRIPADVISOR_RESTAURANT_PAGINATION_CONFIRMED:
                print_category_summary(
                    "Tripadvisor",
                    "Restaurants",
                    len(tripadvisor_restaurants),
                    reviews_for_places(tripadvisor_reviews, tripadvisor_restaurants)
                    if mode != "catalog"
                    else None,
                )
            else:
                print()
                print("=" * 60)
                print("WARNING TRIPADVISOR RESTAURANTS PAGINATION NOT CONFIRMED")
                print(
                    "Restaurants currently collected: "
                    f"{len(tripadvisor_restaurants)}"
                )
                if mode != "catalog":
                    print(
                        "Reviews collected: "
                        f"{reviews_for_places(tripadvisor_reviews, tripadvisor_restaurants)}"
                    )
                print("=" * 60)
        tripadvisor_partial = (
            (only in {"all", "attractions"} and not TRIPADVISOR_ATTRACTION_PAGINATION_CONFIRMED)
            or (only in {"all", "restaurants"} and not TRIPADVISOR_RESTAURANT_PAGINATION_CONFIRMED)
        )
        if tripadvisor_partial:
            print()
            print("=" * 60)
            print("WARNING TRIPADVISOR PARTIAL")
            print("=" * 60)
            print(f"Hotels      : {len(tripadvisor_hotels)}")
            print(f"Attractions : {len(tripadvisor_non_restaurant_attractions)}")
            print(f"Restaurants : {len(tripadvisor_restaurants)}")
            print(f"Reviews     : {len(tripadvisor_reviews)}")
            print("Reason      : one or more catalogue pagination methods are not confirmed")
            print("=" * 60)
        else:
            print_platform_summary(
                "Tripadvisor",
                hotels=len(tripadvisor_hotels),
                attractions=len(tripadvisor_non_restaurant_attractions),
                restaurants=len(tripadvisor_restaurants),
                reviews=len(tripadvisor_reviews),
            )
        hotels = combine_hotels_without_obvious_duplicates(hotels, tripadvisor_hotels)
        reviews.extend(tripadvisor_reviews)
        attractions.extend(tripadvisor_attractions)

    if not hotels and not attractions:
        print("No hotels or attractions were collected.")
        return

    tables = build_all_tables(
        hotels,
        reviews,
        attractions,
        include_availability=include_availability,
        run_type=f"{source}_{mode}",
    )
    tables = save_all_table_outputs(tables)
    save_to_postgres(tables)
    if source == "both":
        print_overall_summary(
            {
                "hotels": len(
                    [
                        hotel
                        for hotel in hotels
                        if hotel.get("source") == "tripadvisor"
                    ]
                ),
                "attractions": len(
                    [
                        place
                        for place in attractions
                        if place.get("source") == "tripadvisor"
                        and is_tripadvisor_attraction(place)
                    ]
                ),
                "restaurants": len(
                    [
                        place
                        for place in attractions
                        if place.get("source") == "tripadvisor"
                        and is_tripadvisor_restaurant(place)
                    ]
                ),
                "reviews": len(
                    [
                        review
                        for review in reviews
                        if review.get("source") == "tripadvisor"
                    ]
                ),
            },
            {
                "hotels": len(
                    [hotel for hotel in hotels if hotel.get("source") == "booking"]
                ),
                "attractions": len(
                    [
                        place
                        for place in attractions
                        if place.get("source") == "booking"
                    ]
                ),
                "reviews": len(
                    [review for review in reviews if review.get("source") == "booking"]
                ),
            },
        )


if __name__ == "__main__":
    ensure_project_dirs()
    args = parse_args()
    with RunLogger(LOG_DIR, source=args.source) as log_path:
        asyncio.run(main(selected_mode(args), args.only, args.source))
        print(f"Completed run. Log saved to: {log_path}")
