from __future__ import annotations

import pandas as pd


def clean_numeric_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    for column in columns:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0)
    return result


def normalize_display_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    for column in result.columns:
        if result[column].dtype == "object":
            result[column] = result[column].fillna("")
    return result
