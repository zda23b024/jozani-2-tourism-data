from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _tail_lines(path: Path, line_count: int = 30) -> list[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            end = handle.tell()
            size = min(end, 64_000)
            handle.seek(end - size)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return [line.rstrip() for line in text.splitlines()[-line_count:]]


def _current_section(lines: list[str]) -> tuple[str | None, str | None]:
    source = None
    entity = None
    for line in lines:
        upper = line.upper()
        if "BOOKING.COM" in upper:
            source = "BOOKING"
        elif "TRIPADVISOR" in upper:
            source = "TRIPADVISOR"

        if "HOTELS" in upper:
            entity = "Hotels"
        elif "ATTRACTIONS" in upper:
            entity = "Attractions"
        elif "RESTAURANTS" in upper:
            entity = "Restaurants"
        elif "REVIEWS" in upper:
            entity = "Reviews"
    return source, entity


def _latest_count(lines: list[str]) -> int | None:
    patterns = (
        re.compile(r"total unique\s+(\d+)", re.IGNORECASE),
        re.compile(r"(?:Hotels|Attractions|Restaurants|Reviews) collected:\s*(\d+)", re.IGNORECASE),
        re.compile(r"Rows processed from .+?:\s*(\d+)", re.IGNORECASE),
    )
    for line in reversed(lines):
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                return int(match.group(1))
    return None


def _latest_page_progress(lines: list[str]) -> dict[str, int | None]:
    page_pattern = re.compile(
        r"Page\s+(?P<page>\d+)\s+\|\s+offset\s+(?P<offset>\d+)\s+\|"
        r"\s+received\s+(?P<received>\d+)\s+\|\s+new\s+(?P<new>\d+)\s+\|"
        r"\s+total unique\s+(?P<total_unique>\d+)",
        re.IGNORECASE,
    )
    for line in reversed(lines):
        match = page_pattern.search(line)
        if match:
            return {key: int(value) for key, value in match.groupdict().items()}
    return {
        "page": None,
        "offset": None,
        "received": None,
        "new": None,
        "total_unique": None,
    }


def _last_meaningful_line(lines: list[str]) -> str | None:
    for line in reversed(lines):
        stripped = line.strip()
        if stripped and not set(stripped) <= {"=", "-"}:
            return stripped
    return None


def _detected_issue(lines: list[str]) -> str | None:
    recent = "\n".join(lines[-20:]).lower()
    if "no search api request was captured" in recent:
        return "Booking.com hotel API request was not captured."
    if "no attractions api request was captured" in recent:
        return "Booking.com attractions API request was not captured."
    if "bad request" in recent or "failed" in recent:
        return "Recent log contains a failure message."
    return None


def latest_log_status(output_dir: str | None = None, stale_seconds: int = 120) -> dict[str, Any]:
    root = Path(output_dir or os.getenv("JOZANI_OUTPUT_DIR", "/app/output"))
    log_dir = root / "logs"
    candidates = sorted(
        [
            *log_dir.glob("booking_run_*.log"),
            *log_dir.glob("tripadvisor_run_*.log"),
            *log_dir.glob("jozani_run_*.log"),
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return {}

    latest = candidates[0]
    lines = _tail_lines(latest)
    now = datetime.now(timezone.utc)
    modified = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
    seconds_since_update = int((now - modified).total_seconds())
    completed = any("Completed run." in line or "COLLECTION COMPLETE" in line for line in lines[-12:])
    active = seconds_since_update <= stale_seconds and not completed
    source, entity = _current_section(lines)
    progress = _latest_page_progress(lines)

    return {
        "log_file": latest.name,
        "status": "RUNNING" if active else "IDLE",
        "source": source or "-",
        "entity": entity or "-",
        "latest_count": _latest_count(lines),
        "page": progress["page"],
        "offset": progress["offset"],
        "received": progress["received"],
        "new": progress["new"],
        "total_unique": progress["total_unique"],
        "last_update": modified,
        "seconds_since_update": seconds_since_update,
        "last_message": _last_meaningful_line(lines),
        "detected_issue": _detected_issue(lines),
        "recent_lines": "\n".join(lines[-18:]),
    }
