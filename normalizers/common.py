"""Shared normalizer helpers."""

from database.models import TABLE_COLUMNS


def empty_table_bundle() -> dict[str, list[dict]]:
    """Return an empty row list for every final database table."""
    return {table_name: [] for table_name in TABLE_COLUMNS}


def merge_table_bundles(*bundles: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Merge several table bundles into one database-ready bundle."""
    merged = empty_table_bundle()
    for bundle in bundles:
        for table_name, rows in bundle.items():
            merged.setdefault(table_name, []).extend(rows)
    return merged
