import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.database import database_url, ensure_database_exists, psycopg


def main() -> None:
    if psycopg is None:
        raise SystemExit("psycopg is not installed.")

    url = database_url()
    if not url:
        raise SystemExit("Database settings are missing.")

    ensure_database_exists()
    with psycopg.connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()

    if result != (1,):
        raise SystemExit(f"Unexpected database response: {result!r}")

    print("Database connection OK.")


if __name__ == "__main__":
    main()
