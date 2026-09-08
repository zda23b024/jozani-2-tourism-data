# Jozani 2.0 Tourism Data Collector

This project is a Booking.com data collection prototype for tourism intelligence. It collects hotel listings, guest reviews, daily prices, availability, policies, amenities, images, and Booking.com attractions for a configured destination.

The current configured destination is Zanzibar City, Tanzania.

The scraper supports Booking.com hotels and attractions plus Tripadvisor hotels, restaurants, attractions, and reviews. For production use, prefer official APIs, partner feeds, exported data, or other permitted access methods where available, and respect each site's terms, robots rules, rate limits, and anti-abuse restrictions. The scraper does not bypass CAPTCHAs or access controls.

## What It Collects

- Hotels and accommodation metadata
- Guest reviews and reviewer details
- Daily price and availability records
- Booking.com attractions and Tripadvisor restaurants
- CSV, JSON, logs, and normalized PostgreSQL records

## Run Jozani

On Windows, the normal interface is:

```text
.\jozani.ps1 <source> <mode>
```

```text
booking      = hotels + attractions
tripadvisor  = hotels + restaurants + attractions
catalog      = place/listing collection only
reviews      = review collection only
all          = catalog + reviews
```

Examples:

```powershell
.\jozani.ps1 booking all
.\jozani.ps1 booking catalog
.\jozani.ps1 booking reviews
.\jozani.ps1 tripadvisor all
.\jozani.ps1 tripadvisor catalog
.\jozani.ps1 tripadvisor reviews
.\jozani.ps1 all all
.\jozani.ps1 all catalog
.\jozani.ps1 all reviews
```

Review commands use existing catalog records from PostgreSQL and do not recollect catalogs.

## Docker

The Docker setup runs the existing backend/data-collection scraper only. There is no FastAPI app in this project and no Alembic configuration; the Python application creates or updates the PostgreSQL schema through `database/create_tables.py`.

Create your Docker environment file:

```powershell
Copy-Item .env.example .env
```

For Docker, keep these values:

```text
PGHOST=db
HEADLESS=true
```

Build the image and start PostgreSQL:

```powershell
docker compose build
docker compose up -d db
```

Initialize or update the database schema:

```powershell
docker compose run --rm app python database/apply_schema.py
```

Run validation checks inside Docker:

```powershell
docker compose run --rm app python tests/docker_db_check.py
docker compose run --rm app python tests/docker_playwright_check.py
docker compose run --rm app python -m unittest discover tests
```

Run the scraper through the wrapper:

```powershell
.\jozani.ps1 booking all
.\jozani.ps1 tripadvisor catalog
.\jozani.ps1 all reviews
```

The wrapper accepts only these sources: `booking`, `tripadvisor`, and `all`. It accepts only these modes: `catalog`, `reviews`, and `all`.

Terminal output is intentionally concise: startup status, verification prompts, collection progress, totals, warnings, and errors remain visible. Complete output is saved in `output/logs`. Set `VERBOSE_LOGS=true` in `.env` when troubleshooting and the full console output will also be shown.

Booking runs through `booking-browser` and displays the browser at `http://localhost:6080/vnc.html`. Tripadvisor runs through `app`. `all` runs Booking first, then Tripadvisor, using the shared PostgreSQL database.

Generated outputs are persisted to the host `output` directory, and browser profiles are persisted to the host `browser` directory.

Stop the Docker services:

```powershell
docker compose down
```

## Streamlit Monitoring Dashboard

The monitoring dashboard is a separate read-only Streamlit service. It reads PostgreSQL statistics only; it does not start, stop, pause, or modify the scraper.

Start PostgreSQL and the dashboard:

```powershell
docker compose up -d db
docker compose up -d dashboard
```

Open:

```text
http://localhost:8501
```

View dashboard logs:

```powershell
docker compose logs -f dashboard
```

Stop only the dashboard:

```powershell
docker compose stop dashboard
```

The collector remains independent. You can run it separately while the dashboard is running:

```powershell
.\jozani.ps1 tripadvisor all
```

For production, create a read-only PostgreSQL user for the dashboard. An example SQL file is provided at `monitoring_dashboard/create_readonly_user.sql`.

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

- scheduled daily execution
- monitoring and alerting
- deployment documentation
- backup and retention policy
- multi-destination management
