import json
import math
from datetime import datetime
from typing import Any

import pandas as pd

from config.configuration import CSV_DIR, JSON_DIR
from database.models import TABLE_COLUMNS, TABLE_CONFLICT_COLUMNS
from utils.helpers import safe_filename


PLATFORM_IDS = ("booking", "tripadvisor", "multi")
COMMON_TABLES = {"sources", "place_types", "locations", "scraping_runs"}


def dataframe_from_rows(
    rows: list[dict],
    columns: list[str],
    conflict_columns: list[str] | None = None,
) -> pd.DataFrame:
    dataframe = pd.DataFrame(rows, columns=columns).astype(object)
    if conflict_columns and all(column in dataframe.columns for column in conflict_columns):
        dataframe = dataframe.drop_duplicates(subset=conflict_columns, keep="first")
    return dataframe.where(pd.notnull(dataframe), None)


def clean_json_value(value: Any) -> Any:
    if value is pd.NA:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {key: clean_json_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [clean_json_value(child) for child in value]
    return value


def clean_json_rows(rows: list[dict]) -> list[dict]:
    return [clean_json_value(row) for row in rows]


def clean_table_rows(table_name: str, rows: list[dict]) -> list[dict]:
    columns = TABLE_COLUMNS[table_name]
    conflict_columns = TABLE_CONFLICT_COLUMNS[table_name]
    dataframe = dataframe_from_rows(rows, columns, conflict_columns)
    return clean_json_rows(dataframe.to_dict(orient="records"))


def source_from_prefixed_value(value: object) -> str | None:
    text = str(value or "")
    for source_id in PLATFORM_IDS:
        if text == source_id or text.startswith(f"{source_id}:"):
            return source_id
    return None


def source_from_row(table_name: str, row: dict) -> str:
    if table_name in COMMON_TABLES:
        return "common"

    for key in [
        "source_id",
        "place_id",
        "place_source_id",
        "review_id",
        "reviewer_id",
        "image_id",
        "offer_id",
        "policy_id",
        "amenity_id",
    ]:
        source_id = source_from_prefixed_value(row.get(key))
        if source_id:
            return source_id
    return "common"


def category_from_row(table_name: str, row: dict) -> str:
    place_id = str(row.get("place_id") or "")
    review_id = str(row.get("review_id") or "")
    combined = f"{place_id} {review_id}".lower()

    if "restaurant" in combined:
        return "restaurants"
    if "attraction" in combined or "activity" in combined:
        return "attractions"
    if table_name in {"accommodations"}:
        return "hotels"
    if table_name in {"restaurants"}:
        return "restaurants"
    if table_name in {"attractions", "activities"}:
        return "attractions"
    return "hotels"


def save_rows_to_paths(
    rows: list[dict],
    columns: list[str],
    csv_path,
    json_path,
    conflict_columns: list[str] | None = None,
) -> list[dict]:
    dataframe = dataframe_from_rows(rows, columns, conflict_columns)
    clean_rows = clean_json_rows(dataframe.to_dict(orient="records"))
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        dataframe.to_csv(csv_path, index=False, encoding="utf-8-sig")
    except PermissionError:
        fallback_csv = csv_path.with_name(
            f"{csv_path.stem}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{csv_path.suffix}"
        )
        dataframe.to_csv(fallback_csv, index=False, encoding="utf-8-sig")
        print(f"CSV locked, saved fallback copy: {fallback_csv.resolve()}")
    try:
        json_path.write_text(
            json.dumps(clean_rows, indent=2, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
    except PermissionError:
        fallback_json = json_path.with_name(
            f"{json_path.stem}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{json_path.suffix}"
        )
        fallback_json.write_text(
            json.dumps(clean_rows, indent=2, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
        print(f"JSON locked, saved fallback copy: {fallback_json.resolve()}")
    return clean_rows


def save_platform_table_files(tables: dict[str, list[dict]]) -> None:
    rows_by_platform: dict[str, dict[str, list[dict]]] = {}
    for table_name, rows in tables.items():
        for row in rows:
            source_id = source_from_row(table_name, row)
            rows_by_platform.setdefault(source_id, {}).setdefault(table_name, []).append(row)

    for source_id, platform_tables in rows_by_platform.items():
        for table_name, rows in platform_tables.items():
            if not rows:
                continue
            save_rows_to_paths(
                rows,
                TABLE_COLUMNS[table_name],
                CSV_DIR / source_id / f"{table_name}.csv",
                JSON_DIR / source_id / f"{table_name}.json",
                TABLE_CONFLICT_COLUMNS[table_name],
            )

        output_label = "common" if source_id == "common" else f"{source_id} platform"
        print(f"{output_label} output saved:", sum(len(v) for v in platform_tables.values()))


def save_platform_review_files(reviews: list[dict]) -> None:
    if not reviews:
        return

    dataframe = pd.DataFrame(reviews, columns=TABLE_COLUMNS["reviews"])
    for (source_id, category, place_id), place_reviews in dataframe.groupby(
        [
            dataframe.apply(lambda row: source_from_row("reviews", row.to_dict()), axis=1),
            dataframe.apply(lambda row: category_from_row("reviews", row.to_dict()), axis=1),
            "place_id",
        ],
        dropna=False,
    ):
        base_name = f"{safe_filename(place_id)}_reviews"
        csv_path = CSV_DIR / source_id / "reviews" / category / f"{base_name}.csv"
        json_path = JSON_DIR / source_id / "reviews" / category / f"{base_name}.json"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.parent.mkdir(parents=True, exist_ok=True)

        save_rows_to_paths(
            place_reviews.to_dict(orient="records"),
            TABLE_COLUMNS["reviews"],
            csv_path,
            json_path,
        )


def save_all_table_outputs(tables: dict[str, list[dict]]) -> dict[str, list[dict]]:
    saved_tables = {}
    for table_name in TABLE_COLUMNS:
        saved_tables[table_name] = clean_table_rows(table_name, tables[table_name])

    save_platform_table_files(saved_tables)
    save_platform_review_files(saved_tables["reviews"])
    return saved_tables
