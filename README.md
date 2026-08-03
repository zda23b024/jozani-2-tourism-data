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
- Reviews are checked by source review ID before scraping/saving.
- Existing reviews are ignored instead of duplicated.
- Review scraping stops when an existing review is encountered.
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
MAX_ATTRACTION_PAGES = 5
MAX_REVIEW_PAGES_PER_HOTEL = 5
HEADLESS = True
```

For Booking.com attractions, `ATTRACTIONS_DEST_ID` must match the destination.

## Running

```powershell
python main.py
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
