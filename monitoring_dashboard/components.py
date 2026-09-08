from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import streamlit as st


STATUS_COLORS = {
    "RUNNING": "#0f766e",
    "STARTED": "#0f766e",
    "COLLECTING": "#0f766e",
    "IN_PROGRESS": "#0f766e",
    "SUCCESS": "#15803d",
    "COMPLETED": "#15803d",
    "FAILED": "#b91c1c",
    "PARTIAL": "#b45309",
    "IDLE": "#475569",
    "UNKNOWN": "#475569",
}


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #f8fafc; }
        section[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e5e7eb; }
        .main .block-container { padding-top: 1.5rem; }
        .jozani-title { color: #172033; font-size: 2.15rem; font-weight: 760; letter-spacing: 0; margin-bottom: 0; }
        .jozani-subtitle { color: #526071; font-size: 1.02rem; margin-top: .15rem; margin-bottom: 1.2rem; }
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: .75rem .85rem;
        }
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: .45rem;
            border-radius: 999px;
            padding: .22rem .68rem;
            color: white;
            font-weight: 700;
            font-size: .78rem;
            letter-spacing: .02rem;
        }
        .section-note { color: #64748b; font-size: .9rem; margin-top: -.35rem; }
        .soft-panel {
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 1rem;
            background: #ffffff;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def title() -> None:
    st.markdown('<div class="jozani-title">JOZANI 2.0</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="jozani-subtitle">Tourism Data Collection Monitor</div>',
        unsafe_allow_html=True,
    )


def format_int(value: Any) -> str:
    if value is None or pd.isna(value):
        return "0"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def format_time(value: Any) -> str:
    if value is None or pd.isna(value):
        return "No data yet"
    if isinstance(value, str):
        return value[:19]
    return value.strftime("%Y-%m-%d %H:%M")


def duration_text(seconds: Any) -> str:
    if seconds is None or pd.isna(seconds):
        return "-"
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def elapsed_from(started_at: Any, completed_at: Any = None) -> str:
    if started_at is None or pd.isna(started_at):
        return "-"
    if isinstance(started_at, str):
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    else:
        started = started_at
    if completed_at is not None and not pd.isna(completed_at):
        completed = completed_at
    else:
        completed = datetime.now(timezone.utc)
    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=timezone.utc)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return duration_text((completed - started).total_seconds())


def status_badge(status: Any) -> str:
    label = str(status or "IDLE").upper()
    color = STATUS_COLORS.get(label, STATUS_COLORS["UNKNOWN"])
    return f'<span class="status-badge" style="background:{color};">{label}</span>'


def dataframe_or_empty(frame: pd.DataFrame, message: str) -> None:
    if frame.empty:
        st.info(message)
        return
    st.dataframe(frame, use_container_width=True, hide_index=True)


def warn_section(title_text: str, error: Exception) -> None:
    print(f"[dashboard] {title_text} failed: {error}")
    st.warning(f"{title_text} unavailable.")
