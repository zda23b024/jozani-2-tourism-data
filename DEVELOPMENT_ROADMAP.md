# Development Roadmap

## Phase 1: Working Prototype

Status: complete

- Booking.com hotel scraping
- Booking.com review scraping
- Booking.com attraction scraping
- PostgreSQL storage
- CSV and JSON exports
- Historical availability records
- Duplicate review prevention
- Incremental review updates
- Production-style page limits
- Run logs

## Phase 2: Ministry Demonstration

Status: ready for preparation

- Prepare presentation slides from `MINISTRY_PRESENTATION_BRIEF.md`
- Run the scraper before the demonstration
- Show PostgreSQL tables and exported CSV files
- Show run logs from `output/logs`
- Demonstrate price and availability history records
- Demonstrate duplicate review prevention using a second run

## Phase 3: Pilot Deployment

Status: recommended next

- Add automated daily scheduling
- Add dashboard/API for users
- Add data quality reports
- Add multi-destination configuration
- Add retry and failure tracking per hotel
- Add automated tests for database insert/update logic
- Add PostgreSQL backup policy

## Phase 4: Production Hardening

Status: future

- Deploy on a managed server
- Add monitoring and alerts
- Add role-based dashboard access
- Add official data retention policy
- Add documentation for operations and maintenance
- Add compliance review for responsible public web data collection
