import hashlib
import json
import re
from typing import Any
from datetime import date as _date, datetime as _datetime

from dateutil.parser import parse as _dateutil_parse

from config.configuration import (
    ADULTS,
    CHECKIN,
    CHECKOUT,
    CHILDREN,
    ROOMS,
)


def nested_get(data: Any, *keys: str) -> Any:
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def first_nonempty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def translation_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return None
    return first_nonempty(
        value.get("text"),
        value.get("translation"),
        value.get("value"),
    )


def join_values(values: list[Any], separator: str = "; ") -> str | None:
    cleaned = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            cleaned.append(text)
    return separator.join(cleaned) if cleaned else None


def safe_filename(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    text = re.sub(r"[^a-z0-9_.-]+", "_", text)
    return (text.strip("_") or "unknown")[:120]


def normalize_booking_url(url: Any) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://www.booking.com" + url
    return url


def normalize_image_url(url: Any) -> str | None:
    return normalize_booking_url(url)


def find_property_url(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in {"url", "uri", "href"}:
                normalized = normalize_booking_url(child)
                if normalized and "/hotel/" in normalized:
                    return normalized
            found = find_property_url(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_property_url(child)
            if found:
                return found
    return None


def hotel_stay_url(hotel: dict[str, Any]) -> str | None:
    property_url = normalize_booking_url(hotel.get("property_url"))
    if not property_url:
        return None
    property_url = property_url.split("?", 1)[0]
    return (
        f"{property_url}?checkin={CHECKIN}"
        f"&checkout={CHECKOUT}"
        f"&group_adults={ADULTS}"
        f"&no_rooms={ROOMS}"
        f"&group_children={CHILDREN}"
    )


def stable_review_id(review: dict[str, Any]) -> str:
    existing = review.get("review_id")
    if existing not in (None, ""):
        return str(existing)
    source = json.dumps(
        [
            review.get("source"),
            review.get("place_id"),
            review.get("place_source_id"),
            review.get("source_place_id"),
            review.get("hotel_id"),
            review.get("reviewer_name"),
            review.get("review_date"),
            review.get("stayed_date"),
            review.get("positive_text"),
            review.get("negative_text"),
            review.get("review_text"),
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def parse_date(value: Any) -> _date | None:
    """Attempt to parse a variety of date inputs to a date object.

    Returns a `datetime.date` when parsing succeeds, otherwise `None`.
    """
    if value is None:
        return None
    if isinstance(value, _datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    try:
        text = str(value).strip()
        if not text:
            return None
        # Let dateutil handle flexible formats
        dt = _dateutil_parse(text, fuzzy=True)
        return dt.date()
    except Exception:
        return None


def limited_rows(
    rows: list[dict[str, Any]],
    columns: list[str],
) -> list[dict[str, Any]]:
    return [{column: row.get(column) for column in columns} for row in rows]
