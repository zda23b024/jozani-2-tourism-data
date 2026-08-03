import json
import math
from typing import Any

from config.database import database_url, ensure_database_exists, psycopg
from database.models import TABLE_COLUMNS, TABLE_CONFLICT_COLUMNS
from utils.helpers import parse_date


ReviewIncrementState = dict[str, Any]


def db_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if value is not value:
            return None
    except Exception:
        pass
    if isinstance(value, float) and math.isnan(value):
        return None
    if value in ("", [], {}):
        return None
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return value


def create_database_tables(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY,
                source_name TEXT NOT NULL,
                source_code TEXT NOT NULL UNIQUE,
                base_url TEXT,
                source_type TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS place_types (
                place_type_id TEXT PRIMARY KEY,
                type_name TEXT NOT NULL UNIQUE,
                type_group TEXT,
                description TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS locations (
                location_id TEXT PRIMARY KEY,
                parent_location_id TEXT REFERENCES locations(location_id),
                location_name TEXT NOT NULL,
                location_type TEXT,
                country TEXT,
                region TEXT,
                district TEXT,
                island TEXT,
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS places (
                place_id TEXT PRIMARY KEY,
                place_type_id TEXT REFERENCES place_types(place_type_id),
                location_id TEXT REFERENCES locations(location_id),
                canonical_name TEXT NOT NULL,
                short_description TEXT,
                latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION,
                status TEXT,
                is_verified BOOLEAN DEFAULT FALSE,
                average_rating DOUBLE PRECISION,
                total_reviews INTEGER,
                sentiment_score DOUBLE PRECISION,
                first_seen_at TIMESTAMPTZ,
                last_seen_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS place_source_records (
                place_source_id TEXT PRIMARY KEY,
                place_id TEXT NOT NULL REFERENCES places(place_id),
                source_id TEXT NOT NULL REFERENCES sources(source_id),
                source_place_id TEXT NOT NULL,
                source_name TEXT,
                source_url TEXT,
                source_category TEXT,
                matching_confidence DOUBLE PRECISION,
                last_scraped_at TIMESTAMPTZ,
                raw_json TEXT,
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ,
                UNIQUE (source_id, source_place_id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS accommodations (
                place_id TEXT PRIMARY KEY REFERENCES places(place_id),
                star_rating DOUBLE PRECISION,
                checkin_time TEXT,
                checkout_time TEXT,
                pets_allowed BOOLEAN,
                child_friendly BOOLEAN,
                beachfront BOOLEAN,
                distance_to_beach TEXT,
                license_number TEXT,
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS attractions (
                place_id TEXT PRIMARY KEY REFERENCES places(place_id),
                attraction_type TEXT,
                entry_fee NUMERIC,
                currency TEXT,
                booking_required BOOLEAN,
                guided_tour BOOLEAN,
                family_friendly BOOLEAN,
                best_visit_time TEXT,
                historical_significance TEXT,
                natural_significance TEXT,
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS amenities (
                amenity_id TEXT PRIMARY KEY,
                amenity_name TEXT NOT NULL UNIQUE,
                amenity_category TEXT,
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS place_amenities (
                place_id TEXT NOT NULL REFERENCES places(place_id),
                amenity_id TEXT NOT NULL REFERENCES amenities(amenity_id),
                is_available BOOLEAN DEFAULT TRUE,
                additional_info TEXT,
                created_at TIMESTAMPTZ,
                PRIMARY KEY (place_id, amenity_id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS images (
                image_id TEXT PRIMARY KEY,
                place_id TEXT NOT NULL REFERENCES places(place_id),
                source_id TEXT REFERENCES sources(source_id),
                image_url TEXT NOT NULL,
                image_hash TEXT,
                image_type TEXT,
                caption TEXT,
                display_order INTEGER,
                is_primary BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reviewers (
                reviewer_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES sources(source_id),
                source_reviewer_id TEXT NOT NULL,
                reviewer_name TEXT,
                country TEXT,
                reviewer_level TEXT,
                profile_image TEXT,
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ,
                UNIQUE (source_id, source_reviewer_id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                review_id TEXT PRIMARY KEY,
                place_id TEXT NOT NULL REFERENCES places(place_id),
                place_source_id TEXT NOT NULL REFERENCES place_source_records(place_source_id),
                reviewer_id TEXT REFERENCES reviewers(reviewer_id),
                source_review_id TEXT NOT NULL,
                review_title TEXT,
                review_text TEXT,
                positive_text TEXT,
                negative_text TEXT,
                review_score DOUBLE PRECISION,
                language TEXT,
                review_date TEXT,
                visit_date TEXT,
                room_name TEXT,
                verified_stay BOOLEAN,
                helpful_votes INTEGER,
                sentiment TEXT,
                emotion TEXT,
                spam_score DOUBLE PRECISION,
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ,
                UNIQUE (place_source_id, source_review_id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS scraping_runs (
                scraping_run_id TEXT PRIMARY KEY,
                source_id TEXT REFERENCES sources(source_id),
                run_type TEXT,
                status TEXT,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                places_found INTEGER,
                places_inserted INTEGER,
                places_updated INTEGER,
                reviews_found INTEGER,
                reviews_inserted INTEGER,
                reviews_skipped INTEGER,
                error_count INTEGER,
                error_message TEXT,
                log_file TEXT,
                created_at TIMESTAMPTZ
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS availability_offers (
                offer_id TEXT PRIMARY KEY,
                place_source_id TEXT NOT NULL REFERENCES place_source_records(place_source_id),
                scraping_run_id TEXT REFERENCES scraping_runs(scraping_run_id),
                checkin DATE,
                checkout DATE,
                adults INTEGER,
                children INTEGER,
                rooms INTEGER,
                room_name TEXT,
                available BOOLEAN,
                price NUMERIC,
                currency TEXT,
                price_per_night NUMERIC,
                breakfast BOOLEAN,
                free_cancellation BOOLEAN,
                scraped_at TIMESTAMPTZ
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS place_policies (
                policy_id TEXT PRIMARY KEY,
                place_id TEXT NOT NULL REFERENCES places(place_id),
                policy_type TEXT,
                policy_text TEXT,
                effective_from DATE,
                effective_to DATE,
                created_at TIMESTAMPTZ
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_places_name ON places(canonical_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_places_location ON places(location_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_places_type ON places(place_type_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_source_records_place ON place_source_records(place_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_source_records_source ON place_source_records(source_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_place ON reviews(place_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_source_record ON reviews(place_source_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(review_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_offers_checkin ON availability_offers(checkin)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_offers_scraped_at ON availability_offers(scraped_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scraping_runs_started ON scraping_runs(started_at)")


def upsert_rows(
    connection: Any,
    table_name: str,
    rows: list[dict],
    columns: list[str],
    conflict_columns: list[str],
) -> None:
    values = [
        tuple(db_value(row.get(column)) for column in columns)
        for row in rows
        if all(row.get(column) not in (None, "") for column in conflict_columns)
    ]

    if not values:
        return

    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    conflict_sql = ", ".join(f'"{column}"' for column in conflict_columns)
    update_columns = [column for column in columns if column not in conflict_columns]

    if table_name == "reviews":
        conflict_action = "DO NOTHING"
    elif update_columns:
        preserve_existing = {
            "created_at",
            "first_seen_at",
        }
        update_sql = ", ".join(
            (
                f'"{column}" = COALESCE("{table_name}"."{column}", '
                f'EXCLUDED."{column}")'
            )
            if column in preserve_existing
            else f'"{column}" = EXCLUDED."{column}"'
            for column in update_columns
        )
        changed_sql = " OR ".join(
            (
                f'"{table_name}"."{column}" IS DISTINCT FROM '
                f'EXCLUDED."{column}"'
            )
            for column in update_columns
            if column not in preserve_existing
        )
        conflict_action = f"DO UPDATE SET {update_sql}"
        if changed_sql:
            conflict_action = f"{conflict_action} WHERE {changed_sql}"
    else:
        conflict_action = "DO NOTHING"

    query = (
        f'INSERT INTO "{table_name}" ({quoted_columns}) '
        f"VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_sql}) {conflict_action}"
    )

    with connection.cursor() as cursor:
        cursor.executemany(query, values)


def fetch_existing_review_state_by_hotel(
    hotels: list[dict],
) -> dict[str, ReviewIncrementState]:
    if psycopg is None:
        return {}

    url = database_url()
    if not url:
        return {}

    ensure_database_exists()
    result: dict[str, ReviewIncrementState] = {}

    try:
        with psycopg.connect(url) as connection:
            create_database_tables(connection)
            with connection.cursor() as cursor:
                for hotel in hotels:
                    hotel_id = hotel.get("hotel_id")
                    if hotel_id in (None, ""):
                        continue
                    hotel_id_text = str(hotel_id)
                    place_source_id = f"booking:listing:{hotel_id_text}"
                    cursor.execute(
                        """
                        SELECT source_review_id, review_date
                        FROM reviews
                        WHERE place_source_id = %s
                        """,
                        (place_source_id,),
                    )
                    rows = cursor.fetchall()
                    source_review_ids = {
                        str(row[0])
                        for row in rows
                        if row and row[0] not in (None, "")
                    }
                    parsed_dates = [
                        parsed
                        for row in rows
                        if len(row) > 1
                        for parsed in [parse_date(row[1])]
                        if parsed is not None
                    ]
                    newest_review_date = (
                        max(parsed_dates).isoformat()
                        if parsed_dates
                        else None
                    )
                    result[hotel_id_text] = {
                        "source_review_ids": source_review_ids,
                        "newest_review_date": newest_review_date,
                    }
            connection.commit()
    except Exception as error:
        print("Incremental review check skipped:", error)
        return {}

    existing_count = sum(
        len(state.get("source_review_ids", set()))
        for state in result.values()
    )
    print(f"Existing review IDs loaded from PostgreSQL: {existing_count}")
    return result


def fetch_existing_review_ids_by_hotel(
    hotels: list[dict],
) -> dict[str, set[str]]:
    state_by_hotel = fetch_existing_review_state_by_hotel(hotels)
    return {
        hotel_id: state.get("source_review_ids", set())
        for hotel_id, state in state_by_hotel.items()
    }


def fetch_existing_review_ids_by_place_source_ids(
    place_source_ids: list[str],
) -> dict[str, set[str]]:
    if psycopg is None:
        return {}

    url = database_url()
    if not url:
        return {}

    ensure_database_exists()
    result: dict[str, set[str]] = {
        place_source_id: set()
        for place_source_id in place_source_ids
        if place_source_id
    }

    if not result:
        return {}

    try:
        with psycopg.connect(url) as connection:
            create_database_tables(connection)
            with connection.cursor() as cursor:
                for place_source_id in result:
                    cursor.execute(
                        """
                        SELECT source_review_id
                        FROM reviews
                        WHERE place_source_id = %s
                        """,
                        (place_source_id,),
                    )
                    rows = cursor.fetchall()
                    result[place_source_id] = {
                        str(row[0])
                        for row in rows
                        if row and row[0] not in (None, "")
                    }
            connection.commit()
    except Exception as error:
        print("Generic incremental review check skipped:", error)
        return {}

    existing_count = sum(len(values) for values in result.values())
    print(f"Existing generic review IDs loaded from PostgreSQL: {existing_count}")
    return result


def save_to_postgres(tables: dict[str, list[dict]]) -> None:
    if psycopg is None:
        print("PostgreSQL save skipped: psycopg is not installed.")
        return

    url = database_url()
    if not url:
        print("PostgreSQL save skipped: database settings are missing.")
        return

    ensure_database_exists()

    with psycopg.connect(url) as connection:
        create_database_tables(connection)
        for table_name, columns in TABLE_COLUMNS.items():
            upsert_rows(
                connection,
                table_name,
                tables.get(table_name, []),
                columns,
                TABLE_CONFLICT_COLUMNS[table_name],
            )
        connection.commit()

    print("PostgreSQL save completed.")
    for table_name in TABLE_COLUMNS:
        print(f'Rows sent to "{table_name}": {len(tables.get(table_name, []))}')
