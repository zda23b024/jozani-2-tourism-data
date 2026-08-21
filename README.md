# Booking.com Tourism Data Collector

This project is a Booking.com data collection prototype for tourism intelligence. It collects hotel listings, guest reviews, daily prices, availability, policies, amenities, images, and Booking.com attractions for a configured destination.

The current configured destination is Zanzibar City, Tanzania.

## What It Collects

- Hotels and accommodation metadata
- Guest reviews and reviewer details
- Daily price and availability records
- Check-in and check-out dates
- Hotel policies, amenities, and images
- Booking.com attractions and activity availability
- Scraping run history

## Production-Oriented Logic

- Hotels are inserted when new and updated when already present.
- Reviews are scraped through all available pages returned by Booking.com.
- Existing reviews are upserted instead of duplicated.
- Availability offers are stored historically for each scrape run.
- Each run writes a timestamped log file under `output/logs`.

## Project Structure

```text
config/       Destination, date, browser, and database settings
database/     PostgreSQL schema creation and save logic
normalizers/  Conversion from scraped JSON to database-ready rows
scraper/      Booking.com hotel, review, and attraction scraping
utils/        Browser helpers, file output, IDs, date parsing, run logging
output/       Generated CSV, JSON, and log files
main.py       Main application entrypoint
```

## Requirements

- Python 3.11 or newer
- PostgreSQL
- Playwright Chromium

Install dependencies:

```powershell
pip install -r requirements.txt
playwright install chromium
```

## Database Setup

Create a `.env` file using `.env.example` as the template.

Recommended production database name:

```text
booking_reviews_prod
```

Example:

```text
PGHOST=localhost
PGPORT=5432
PGDATABASE=booking_reviews_prod
PGUSER=postgres
PGPASSWORD=your_password
```

The system will create required tables automatically when it runs.

## Configuration

Main settings are in `config/configuration.py`.

```python
SEARCH_TERM = "Zanzibar City"
SEARCH_COUNTRY = "Tanzania"
SEARCH_REGION = "Zanzibar"
SEARCH_ISLAND = "Unguja"

MAX_HOTEL_PAGES = 10
MAX_ATTRACTION_PAGES = 10
MAX_REVIEW_PAGES_PER_HOTEL = None
HEADLESS = False
```

For Booking.com attractions, `ATTRACTIONS_DEST_ID` must match the destination.

## Running

```powershell
python main.py
```

Default daily run:

```powershell
python main.py
```

This collects today's date-based prices and availability, plus new reviews.

Full base dataset run:

```powershell
python main.py --all
```

This collects the hotel and attraction catalog plus reviews, without saving date-based availability offers.
Hotel discovery uses undated Booking.com catalog searches across configured Zanzibar areas, then deduplicates by Booking.com hotel ID. Attraction discovery uses undated Booking.com attraction destination IDs from `CATALOG_ATTRACTION_DESTINATIONS`, then deduplicates by Booking.com attraction ID.

The default Zanzibar hotel catalog areas are:

```text
Zanzibar City, Stone Town, Nungwi, Kendwa, Paje, Bwejuu,
Jambiani, Kiwengwa, Matemwe, Michamvi, Pingwe, Uroa,
Kizimkazi, Makunduchi, Dongwe, Pwani Mchangani, Pongwe,
Chwaka, Mangapwani
```

The default attraction catalog destination is:

```text
Zanzibar: -2574828
```

Add more Booking.com attraction destination IDs to `CATALOG_ATTRACTION_DESTINATIONS` in `config/configuration.py` when they are discovered.

Review-only run:

```powershell
python main.py --reviews
```

This loads known Booking.com hotels and attractions from PostgreSQL and collects all review pages currently available from Booking.com.

Catalog-only refresh:

```powershell
python main.py --catalog
```

This refreshes stable hotel and attraction details without reviews or date-based availability offers.
Hotel and attraction discovery use the same undated catalog searches as `--all`.

Optional limiter:

```powershell
python main.py --daily --only hotels
python main.py --daily --only attractions
```

Each run saves:

- CSV output under `output/csv`
- JSON output under `output/json`
- A run log under `output/logs`
- Normalized records into PostgreSQL

## Key Database Tables

- `places`
- `place_source_records`
- `accommodations`
- `attractions`
- `reviews`
- `reviewers`
- `availability_offers`
- `place_policies`
- `scraping_runs`

## Current Status

This is a working development prototype suitable for demonstration and further pilot development. Before national-scale production, recommended additions are:

- dashboard or API for viewing data
- automated tests
- scheduled daily execution
- monitoring and alerting
- deployment documentation
- backup and retention policy
- multi-destination management
