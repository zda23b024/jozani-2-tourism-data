import os
from contextlib import contextmanager
from urllib.parse import quote_plus

import pandas as pd
import psycopg
from psycopg.rows import dict_row


WRITE_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "TRUNCATE",
    "ALTER",
    "CREATE",
    "GRANT",
    "REVOKE",
}


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def database_url() -> str:
    direct_url = env("DATABASE_URL")
    if direct_url:
        return direct_url

    host = env("PGHOST", "db")
    port = env("PGPORT", "5432")
    database = env("PGDATABASE", "zanzibar_booking_data")
    user = env("PGUSER", "postgres")
    password = env("PGPASSWORD", "")

    return (
        f"postgresql://{quote_plus(user)}:"
        f"{quote_plus(password)}@{host}:{port}/"
        f"{quote_plus(database)}"
    )


def refresh_seconds() -> int:
    try:
        return max(10, int(env("DASHBOARD_REFRESH_SECONDS", "30")))
    except ValueError:
        return 30


def assert_select_only(query: str) -> None:
    normalized = query.strip().upper()
    if not normalized.startswith(("SELECT", "WITH")):
        raise ValueError("Dashboard queries must be SELECT-only.")
    words = {
        token.strip("(),;")
        for token in normalized.replace("\n", " ").split()
    }
    blocked = WRITE_KEYWORDS.intersection(words)
    if blocked:
        raise ValueError(f"Write SQL is not allowed in dashboard query: {sorted(blocked)}")


@contextmanager
def connection():
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        yield conn


def query_dataframe(query: str, params: tuple = ()) -> pd.DataFrame:
    assert_select_only(query)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
    return pd.DataFrame(rows)


def query_one(query: str, params: tuple = ()) -> dict:
    frame = query_dataframe(query, params)
    if frame.empty:
        return {}
    return frame.iloc[0].to_dict()
