from __future__ import annotations

import json
import sys
from ast import literal_eval
from csv import DictReader
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.configuration import JSON_DIR
from database.create_tables import save_to_postgres
from database.models import TABLE_COLUMNS


OUTPUT_SOURCES = ("common", "booking", "tripadvisor")


def read_json_table(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON list.")
    return data


def read_csv_table(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {key: clean_csv_value(key, value) for key, value in row.items()}
            for row in DictReader(handle)
        ]


def clean_csv_value(key: str, value: str | None) -> Any:
    if value in (None, ""):
        return None
    stripped = value.strip()
    lower = stripped.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if key == "raw_json":
        return clean_raw_json(stripped)
    return stripped


def clean_raw_json(value: str) -> str:
    try:
        json.loads(value)
        return value
    except json.JSONDecodeError:
        pass

    try:
        parsed = literal_eval(value)
    except (SyntaxError, ValueError):
        return "{}"
    if isinstance(parsed, (dict, list)):
        return json.dumps(parsed, ensure_ascii=False)
    return "{}"


def row_count(path: Path) -> int:
    if not path.exists():
        return -1
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            return max(sum(1 for _ in handle) - 1, 0)
    return len(read_json_table(path))


def choose_table_file(source_name: str, table_name: str) -> tuple[Path, str] | None:
    json_path = JSON_DIR / source_name / f"{table_name}.json"
    csv_path = JSON_DIR.parent / "csv" / source_name / f"{table_name}.csv"
    json_rows = row_count(json_path)
    csv_rows = row_count(csv_path)

    if json_rows < 0 and csv_rows < 0:
        return None
    if csv_rows > json_rows:
        return csv_path, "csv"
    if csv_rows == json_rows and csv_path.exists() and json_path.exists():
        if csv_path.stat().st_mtime > json_path.stat().st_mtime:
            return csv_path, "csv"
    if json_path.exists():
        return json_path, "json"
    return csv_path, "csv"


def load_saved_tables() -> dict[str, list[dict[str, Any]]]:
    tables: dict[str, list[dict[str, Any]]] = {table_name: [] for table_name in TABLE_COLUMNS}

    for source_name in OUTPUT_SOURCES:
        for table_name in TABLE_COLUMNS:
            chosen = choose_table_file(source_name, table_name)
            if chosen is None:
                continue
            path, format_name = chosen
            rows = read_csv_table(path) if format_name == "csv" else read_json_table(path)
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
