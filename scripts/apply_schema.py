import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.database import database_url, ensure_database_exists, psycopg
from database.create_tables import create_database_tables


def main() -> None:
    if psycopg is None:
        raise SystemExit("psycopg is not installed.")

    url = database_url()
    if not url:
        raise SystemExit("Database settings are missing.")

    ensure_database_exists()
    with psycopg.connect(url) as connection:
        create_database_tables(connection)
        connection.commit()

    print("Database schema is ready.")


if __name__ == "__main__":
    main()
