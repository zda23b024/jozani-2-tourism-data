from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.configuration import JSON_DIR
from database.create_tables import save_to_postgres
from database.models import TABLE_COLUMNS


OUTPUT_SOURCES = ("common", "booking", "tripadvisor")


def read_table_file(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON list.")
    return data


def load_saved_tables() -> dict[str, list[dict[str, Any]]]:
    tables: dict[str, list[dict[str, Any]]] = {table_name: [] for table_name in TABLE_COLUMNS}

    for source_name in OUTPUT_SOURCES:
        source_dir = JSON_DIR / source_name
        if not source_dir.exists():
            continue

        for table_name in TABLE_COLUMNS:
            path = source_dir / f"{table_name}.json"
            if not path.exists():
                continue
            rows = read_table_file(path)
            tables[table_name].extend(rows)
            print(f"Loaded {len(rows):,} rows from {path.relative_to(ROOT_DIR)}")

    return tables


def main() -> None:
    tables = load_saved_tables()
    total_rows = sum(len(rows) for rows in tables.values())
    if total_rows == 0:
        raise SystemExit(f"No saved JSON table rows found in {JSON_DIR}.")

    print(f"\nSaving {total_rows:,} loaded rows to PostgreSQL...")
    save_to_postgres(tables)
    print("Saved loaded output files to PostgreSQL.")


if __name__ == "__main__":
    main()
