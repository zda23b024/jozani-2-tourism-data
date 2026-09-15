# Jozani 2.0 Tourism Data Collector

Jozani 2.0 Tourism Data Collector is a multi-source tourism data acquisition, integration, and monitoring prototype developed as part of the **Jozani 2.0 Tourism Intelligence Platform**.

The project collects structured tourism information and visitor reviews from supported online tourism platforms, normalizes data from different sources into a common structure, stores the resulting records in PostgreSQL, and provides a read-only monitoring dashboard for inspecting the collected dataset and collection status.

The current implementation focuses on tourism data for **Zanzibar, Tanzania**.

Currently supported sources are:

- **Booking.com** — accommodations, attractions, and reviews
- **Tripadvisor** — hotels, restaurants, attractions, and reviews

For production use, official APIs, partner feeds, licensed datasets, exported data, or other permitted access methods should be preferred where available. Collection should comply with each source's applicable terms, robots rules, rate limits, and access restrictions. The project does not bypass CAPTCHAs or access controls.

## What It Collects

The current data acquisition pipeline supports:

- Hotels and accommodation metadata
- Tourism attractions and activities
- Restaurants
- Visitor and guest reviews
- Reviewer information
- Ratings and review metadata
- Prices and availability where available
- Amenities and facilities
- Policies
- Images and source URLs
- Source-specific tourism records
- Collection and scraping metadata

Collected data is standardized and stored in a normalized PostgreSQL database. CSV and JSON outputs, logs, and debugging artifacts are also generated where applicable.

## Project Architecture

The current data flow is:

```text
Booking.com ──────┐
                  ├──> Source Collectors
Tripadvisor ──────┘
                          │
                          ▼
                Parsing & Normalization
                          │
                          ▼
               Deduplication & Mapping
                          │
                          ▼
                     PostgreSQL
                          │
                          ▼
               Monitoring Dashboard
```

The architecture keeps source-specific records while maintaining normalized tourism entities in PostgreSQL. This allows data from multiple tourism platforms to be integrated without losing the identity of the original source records.

## Run Jozani

On Windows, the normal interface is:

```text
.\jozani.ps1 <source> <mode>
```

Supported sources:

```text
booking      = accommodations + attractions
tripadvisor  = hotels + restaurants + attractions
all          = Booking.com + Tripadvisor
```

Supported modes:

```text
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

Review commands use existing catalog records from PostgreSQL and do not recollect the catalog.

## Data Collection Design

Booking.com and Tripadvisor use separate source collectors because their page structures, identifiers, review formats, pagination mechanisms, and available metadata differ.

The collected records are transformed into a common normalized representation before being stored in PostgreSQL.

The pipeline includes mechanisms for:

- source-aware place identification
- review identification and deduplication
- pagination
- data normalization
- structured review extraction
- fallback review extraction where supported
- collection logging
- error handling
- debugging artifacts
- PostgreSQL persistence

Collection failures or unavailable review information are not automatically interpreted as confirmed zero-review records.

## Docker

The Docker environment runs the existing backend/data-collection system. There is no FastAPI application and no Alembic configuration in this project.

The Python application creates and updates the PostgreSQL schema using the existing database modules.

Create the Docker environment file:

```powershell
Copy-Item .env.example .env
```

For Docker, keep:

```text
PGHOST=db
HEADLESS=true
```

Build the application image and start PostgreSQL:

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

Run the collectors through the wrapper:

```powershell
.\jozani.ps1 booking all
.\jozani.ps1 tripadvisor catalog
.\jozani.ps1 all reviews
```

The wrapper accepts the following sources:

```text
booking
tripadvisor
all
```

and the following modes:

```text
catalog
reviews
all
```

Terminal output is intentionally concise. Important startup information, collection progress, totals, warnings, and errors remain visible.

Complete run logs are stored in:

```text
output/logs
```

Set:

```text
VERBOSE_LOGS=true
```

in `.env` when additional troubleshooting output is required.

### Booking Browser

Booking.com collection that requires browser interaction runs through the `booking-browser` service.

The browser can be viewed locally at:

```text
http://localhost:6080/vnc.html
```

Tripadvisor collection runs through the `app` service.

When:

```powershell
.\jozani.ps1 all all
```

is used, Booking.com and Tripadvisor collection run sequentially against the shared PostgreSQL database.

Generated outputs are persisted in the host `output` directory, while browser profiles are stored in the host `browser` directory.

Stop Docker services with:

```powershell
docker compose down
```

## Streamlit Monitoring Dashboard

The project includes a separate read-only Streamlit monitoring dashboard.

The dashboard reads statistics and tourism data from PostgreSQL. It does **not** start, stop, pause, or modify the collectors.

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

The data collectors remain independent and can run while the dashboard is active:

```powershell
.\jozani.ps1 tripadvisor all
```

For production environments, a dedicated read-only PostgreSQL account should be used by the dashboard.

An example configuration is provided in:

```text
monitoring_dashboard/create_readonly_user.sql
```

## PostgreSQL Data Model

The PostgreSQL database uses a normalized, source-aware structure for integrating tourism information from multiple platforms.

Important tables include:

- `sources`
- `place_types`
- `locations`
- `places`
- `place_source_records`
- `accommodations`
- `attractions`
- `restaurants`
- `reviews`
- `reviewers`
- `review_responses`
- `review_category_scores`
- `availability_offers`
- `place_policies`
- `scraping_runs`

### Canonical Places and Source Records

`places` represents normalized tourism entities.

`place_source_records` stores the corresponding source-specific representation from Booking.com, Tripadvisor, or another supported source.

This separation allows the system to retain source provenance while supporting integration and deduplication across multiple tourism platforms.

Reviews are associated with the appropriate source records so that their original platform context is preserved.

## Repository Structure

```text
jozani-2-tourism-data/
│
├── config/                  # Project and environment configuration
├── database/                # PostgreSQL schema and persistence
├── monitoring_dashboard/    # Read-only Streamlit monitoring dashboard
├── normalizers/             # Cross-source data normalization
├── scraper/
│   ├── booking/             # Booking.com collectors
│   └── tripadvisor/         # Tripadvisor collectors
├── tests/                   # Automated and environment validation tests
├── utils/                   # Shared utilities
├── output/                  # Generated data, logs and debugging output
├── browser/                 # Local browser profiles
│
├── main.py                  # Main collection entry point
├── jozani.ps1               # Windows command wrapper
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

## Monitoring and Validation

The system records collection activity and provides information that can be used to monitor:

- collected tourism places
- source coverage
- collected reviews
- collection runs
- database status
- review-text availability
- category distribution
- recent collection activity

The dashboard obtains these values directly from PostgreSQL rather than using hard-coded statistics.

## Current Status

Jozani 2.0 Tourism Data Collector is currently a **working development prototype for multi-source tourism data acquisition, normalization, storage, and monitoring**.

The current phase provides the data foundation required by other components of the broader Jozani 2.0 Tourism Intelligence Platform.

Current implemented capabilities include:

- Booking.com tourism data collection
- Tripadvisor tourism data collection
- accommodation, attraction, and restaurant collection
- visitor review collection
- review pagination and deduplication
- cross-source data normalization
- normalized PostgreSQL storage
- Docker-based execution
- structured logging and debugging
- read-only Streamlit monitoring dashboard

Future production hardening may include:

- scheduled collection execution
- operational monitoring and alerting
- production deployment documentation
- database backup and retention policies
- multi-destination configuration and management
- additional authorized tourism data integrations

## Project Scope

This repository focuses on the **tourism data acquisition and integration layer** of Jozani 2.0.

AI analytics, sentiment analysis, aspect-based analysis, predictive intelligence, and the final public-facing tourism platform are outside the current implementation scope of this repository.
