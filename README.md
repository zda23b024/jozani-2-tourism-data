# Jozani 2.0 Tourism Data Collector

Jozani 2.0 Tourism Data Collector is a local-first tourism data acquisition, normalization, PostgreSQL storage, and monitoring project for Zanzibar tourism data.

The project collects structured tourism places and reviews from supported tourism platforms, normalizes the records into a source-aware PostgreSQL schema, writes CSV/JSON/log outputs, and provides a read-only Streamlit monitoring dashboard.

Supported sources:

- **Booking.com**: accommodations, attractions, reviews
- **Tripadvisor**: hotels, attractions, restaurants, reviews

For production use, official APIs, partner feeds, licensed datasets, exported data, or other permitted access methods should be preferred where available. Collection should comply with each source's applicable terms, robots rules, rate limits, and access restrictions. The project does not bypass CAPTCHAs or access controls.

## Architecture

```text
Booking.com
    |
Tripadvisor
    |
    v
Python collectors (local .venv + Playwright)
    |
    v
Parsing, normalization, and deduplication
    |
    v
Local PostgreSQL (localhost:5432)
    |
    v
Streamlit monitoring dashboard (localhost:8501)
```

PostgreSQL is the source of truth. The dashboard reads live values from PostgreSQL and does not hardcode metrics.

## Requirements

- Windows
- Python 3.12 or compatible Python 3.x
- Local PostgreSQL
- Playwright Chromium
- Python virtual environment at `.venv`

## Setup

Create and activate the local Python environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```

Create local configuration:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set your local PostgreSQL credentials:

```text
PGHOST=localhost
PGPORT=5432
PGDATABASE=zanzibar_booking_data
PGUSER=postgres
PGPASSWORD=change_this_password
```

Dashboard-specific database settings can use the same database:

```text
DASHBOARD_PGHOST=localhost
DASHBOARD_PGPORT=5432
DASHBOARD_PGDATABASE=zanzibar_booking_data
DASHBOARD_DB_USER=postgres
DASHBOARD_DB_PASSWORD=change_this_password
```

Do not commit `.env`.

## Database Setup

Initialize or update the existing PostgreSQL schema:

```powershell
.\.venv\Scripts\python.exe database\apply_schema.py
```

This uses the existing schema modules in `database/`. It does not reset or drop collected data.

## Run Collection

The main Python CLI uses flags:

```powershell
.\.venv\Scripts\python.exe main.py --catalog --source booking
.\.venv\Scripts\python.exe main.py --reviews --source booking
.\.venv\Scripts\python.exe main.py --all --source booking

.\.venv\Scripts\python.exe main.py --catalog --source tripadvisor
.\.venv\Scripts\python.exe main.py --reviews --source tripadvisor
.\.venv\Scripts\python.exe main.py --all --source tripadvisor

.\.venv\Scripts\python.exe main.py --catalog --source both
.\.venv\Scripts\python.exe main.py --reviews --source both
.\.venv\Scripts\python.exe main.py --all --source both
```

The Windows convenience wrapper maps simple positional commands to the same Python CLI:

```powershell
.\jozani.ps1 booking catalog
.\jozani.ps1 booking reviews
.\jozani.ps1 booking all

.\jozani.ps1 tripadvisor catalog
.\jozani.ps1 tripadvisor reviews
.\jozani.ps1 tripadvisor all

.\jozani.ps1 all catalog
.\jozani.ps1 all reviews
.\jozani.ps1 all all
```

Review commands use existing catalog records from PostgreSQL.

## Browser Behavior

The collectors use local Playwright Chromium.

```text
HEADLESS=true
```

runs Chromium without opening a visible browser window.

```text
HEADLESS=false
```

opens the local Playwright Chromium browser window on Windows.

Persistent browser profiles are stored under:

```text
browser/
```

## Run Dashboard

Start the monitoring dashboard:

```powershell
.\.venv\Scripts\python.exe -m streamlit run monitoring_dashboard\app.py
```

or:

```powershell
.\start-dashboard.ps1
```

Open:

```text
http://localhost:8501
```

The dashboard remains read-only and includes:

- Overview
- Data Explorer
- Reviews
- Collection Health
- Database
- PostgreSQL connection status
- source coverage and review metrics

## Output

Generated files are written under:

```text
output/csv
output/json
output/logs
output/debug
```

Browser profiles and session/cache files are local runtime artifacts and are ignored by Git.

## Useful Local Checks

Check Python:

```powershell
.\.venv\Scripts\python.exe --version
```

Check imports:

```powershell
.\.venv\Scripts\python.exe -c "import sqlalchemy; import playwright; import streamlit; print('OK')"
```

Check PostgreSQL connection:

```powershell
.\.venv\Scripts\python.exe tests\local_db_check.py
```

Check Playwright Chromium:

```powershell
.\.venv\Scripts\python.exe tests\local_playwright_check.py
```

Run automated tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover tests
```

## PostgreSQL Data Model

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

`places` stores normalized tourism entities. `place_source_records` stores the source-specific listing from Booking.com or Tripadvisor. Reviews are linked to source records so source ownership remains clear.

## Repository Structure

```text
jozani-2-tourism-data/
|
|-- config/
|-- database/
|-- monitoring_dashboard/
|-- normalizers/
|-- scraper/
|   |-- booking/
|   `-- tripadvisor/
|-- tests/
|-- utils/
|-- output/
|-- browser/
|
|-- .env.example
|-- .gitignore
|-- jozani.ps1
|-- start-dashboard.ps1
|-- main.py
|-- README.md
`-- requirements.txt
```

## Current Scope

This repository focuses on the tourism data acquisition and integration layer:

- multi-source collection
- source-specific parsing
- normalization and deduplication
- PostgreSQL persistence
- CSV/JSON/log outputs
- Streamlit monitoring

AI analytics, sentiment analysis, predictive intelligence, and a public tourism portal are outside the current scope of this repository.

## Normal Workflow

Setup once:

```text
create .venv
install requirements
install Playwright Chromium
configure .env
initialize/verify PostgreSQL
```

Daily collection:

```powershell
.\jozani.ps1 booking reviews
.\jozani.ps1 tripadvisor reviews
```

Monitoring:

```powershell
.\start-dashboard.ps1
```

Then open:

```text
http://localhost:8501
```
