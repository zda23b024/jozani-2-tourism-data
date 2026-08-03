import asyncio

from config.configuration import BOOKING_BROWSER_PROFILE_DIR, LOG_DIR, ensure_project_dirs
from database.create_tables import fetch_existing_review_state_by_hotel, save_to_postgres
from normalizers.table_builder import build_all_tables
from scraper.booking.scrape_attractions import scrape_attractions_in_context
from scraper.booking.scrape_reviews import scrape_reviews_for_hotels
from scraper.booking.scrape_stays import scrape_hotels_in_context
from utils.browser_helpers import close_context, launch_context
from utils.file_manager import save_all_table_outputs
from utils.run_logging import RunLogger


async def main() -> None:
    ensure_project_dirs()
    hotels = []
    reviews = []
    attractions = []

    booking_context = await launch_context(
        BOOKING_BROWSER_PROFILE_DIR,
        "Booking.com",
    )
    try:
        hotels = await scrape_hotels_in_context(booking_context)

        if hotels:
            existing_review_state = fetch_existing_review_state_by_hotel(hotels)
            reviews = await scrape_reviews_for_hotels(
                booking_context,
                hotels,
                existing_review_state,
            )

        attractions = await scrape_attractions_in_context(booking_context)
    finally:
        await close_context(booking_context)

    if not hotels and not attractions:
        print("No hotels or attractions were collected.")
        return

    tables = build_all_tables(hotels, reviews, attractions)
    tables = save_all_table_outputs(tables)
    save_to_postgres(tables)


if __name__ == "__main__":
    ensure_project_dirs()
    with RunLogger(LOG_DIR) as log_path:
        asyncio.run(main())
        print(f"Completed run. Log saved to: {log_path}")
