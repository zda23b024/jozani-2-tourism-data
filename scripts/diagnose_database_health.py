import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.database import database_url, psycopg


QUERIES = [
    ("places", "SELECT COUNT(*) FROM places"),
    ("place_source_records", "SELECT COUNT(*) FROM place_source_records"),
    ("reviews", "SELECT COUNT(*) FROM reviews"),
    ("reviewers", "SELECT COUNT(*) FROM reviewers"),
    (
        "booking_places",
        """
        SELECT COUNT(*)
        FROM place_source_records psr
        JOIN sources s ON s.source_id = psr.source_id
        WHERE s.source_code = 'BOOKING'
        """,
    ),
    (
        "tripadvisor_places",
        """
        SELECT COUNT(*)
        FROM place_source_records psr
        JOIN sources s ON s.source_id = psr.source_id
        WHERE s.source_code = 'TRIPADVISOR'
        """,
    ),
    (
        "booking_reviews",
        """
        SELECT COUNT(*)
        FROM reviews r
        JOIN place_source_records psr ON psr.place_source_id = r.place_source_id
        JOIN sources s ON s.source_id = psr.source_id
        WHERE s.source_code = 'BOOKING'
        """,
    ),
    (
        "tripadvisor_reviews",
        """
        SELECT COUNT(*)
        FROM reviews r
        JOIN place_source_records psr ON psr.place_source_id = r.place_source_id
        JOIN sources s ON s.source_id = psr.source_id
        WHERE s.source_code = 'TRIPADVISOR'
        """,
    ),
    (
        "orphan_reviews",
        """
        SELECT COUNT(*)
        FROM reviews r
        LEFT JOIN place_source_records psr ON psr.place_source_id = r.place_source_id
        WHERE psr.place_source_id IS NULL
        """,
    ),
    (
        "orphan_source_records",
        """
        SELECT COUNT(*)
        FROM place_source_records psr
        LEFT JOIN places p ON p.place_id = psr.place_id
        WHERE p.place_id IS NULL
        """,
    ),
]

SCHEMA_CHECKS = [
    (
        "new_tables",
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name IN (
            'attraction_source_details',
            'restaurant_source_details',
            'operating_hours'
          )
        ORDER BY table_name
        """,
    ),
    (
        "review_columns",
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'reviews'
          AND column_name IN (
            'rating_scale',
            'trip_type',
            'stay_date',
            'original_language_code',
            'is_machine_translated',
            'is_verified',
            'source_url'
          )
        ORDER BY column_name
        """,
    ),
    (
        "source_record_ranking_columns",
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'place_source_records'
          AND column_name IN (
            'ranking_total',
            'ranking_text',
            'ranking_category'
          )
        ORDER BY column_name
        """,
    ),
]


def main() -> None:
    if psycopg is None:
        raise SystemExit("psycopg is not installed")
    url = database_url()
    if not url:
        raise SystemExit("database settings are missing")
    with psycopg.connect(url) as connection:
        with connection.cursor() as cursor:
            for label, query in QUERIES:
                cursor.execute(query)
                print(f"{label}: {cursor.fetchone()[0]}")
            for label, query in SCHEMA_CHECKS:
                cursor.execute(query)
                values = ", ".join(row[0] for row in cursor.fetchall())
                print(f"{label}: {values}")


if __name__ == "__main__":
    main()
