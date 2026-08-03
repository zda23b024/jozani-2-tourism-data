import os
from pathlib import Path
from urllib.parse import quote_plus

try:
    import psycopg
    from psycopg import sql as psycopg_sql
except ImportError:
    psycopg = None
    psycopg_sql = None


def load_env_file() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(
            key.strip(),
            value.strip().strip('"').strip("'"),
        )


def database_url() -> str | None:
    load_env_file()
    direct_url = os.getenv("DATABASE_URL")
    if direct_url:
        return direct_url

    host = os.getenv("PGHOST")
    database = os.getenv("PGDATABASE")
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    port = os.getenv("PGPORT", "5432")

    if not all([host, database, user, password]):
        return None

    return (
        f"postgresql://{quote_plus(user)}:"
        f"{quote_plus(password)}@{host}:{port}/"
        f"{quote_plus(database)}"
    )


def ensure_database_exists() -> None:
    load_env_file()

    if psycopg is None or psycopg_sql is None or os.getenv("DATABASE_URL"):
        return

    host = os.getenv("PGHOST")
    database = os.getenv("PGDATABASE")
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    port = os.getenv("PGPORT", "5432")

    if not all([host, database, user, password]):
        return

    with psycopg.connect(
        host=host,
        port=port,
        dbname="postgres",
        user=user,
        password=password,
        autocommit=True,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (database,),
            )
            if cursor.fetchone():
                return
            cursor.execute(
                psycopg_sql.SQL("CREATE DATABASE {}").format(
                    psycopg_sql.Identifier(database)
                )
            )
            print(f'Created PostgreSQL database "{database}".')
