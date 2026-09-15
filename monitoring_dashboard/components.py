from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import streamlit as st


STATUS_COLORS = {
    "RUNNING": "#2563eb",
    "STARTED": "#2563eb",
    "COLLECTING": "#2563eb",
    "IN_PROGRESS": "#2563eb",
    "SUCCESS": "#15803d",
    "COMPLETED": "#15803d",
    "COMPLETE": "#15803d",
    "FAILED": "#b91c1c",
    "ERROR": "#b91c1c",
    "PARTIAL": "#b45309",
    "WARNING": "#b45309",
    "WARN": "#b45309",
    "IDLE": "#475569",
    "UNKNOWN": "#475569",
}


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --jozani-bg: #f7f8fa;
            --jozani-card: #ffffff;
            --jozani-text: #172033;
            --jozani-muted: #64748b;
            --jozani-border: #e6e8ef;
            --jozani-crimson: #8f1027;
            --jozani-crimson-dark: #730d20;
            --jozani-gold: #c6922e;
        }
        html, body, .stApp { background: var(--jozani-bg); color: var(--jozani-text); font-family: Inter, "Segoe UI", Roboto, Arial, sans-serif; }
        #MainMenu, footer, header,
        [data-testid="stHeader"] {
            display: none !important;
            visibility: hidden !important;
            height: 0 !important;
            min-height: 0 !important;
        }
        [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"] {
            display: none !important;
            visibility: hidden !important;
            height: 0 !important;
        }
        [data-testid="stAppViewContainer"] {
            padding-top: 0 !important;
            margin-top: 0 !important;
        }
        main[data-testid="stMain"] {
            padding-top: 0 !important;
            margin-top: 0 !important;
        }
        div[data-testid="stMainBlockContainer"] {
            padding-top: .15rem !important;
            padding-left: .8rem !important;
            padding-right: .8rem !important;
            max-width: none !important;
        }
        div[data-testid="stAppViewBlockContainer"] {
            padding-top: .15rem !important;
            max-width: none !important;
        }
        .block-container {
            padding-top: .15rem !important;
            margin-top: 0 !important;
        }
        section[data-testid="stSidebar"] {
            background: #ffffff;
            border-right: 1px solid var(--jozani-border);
            box-shadow: 4px 0 18px rgba(15, 23, 42, .04);
            min-width: 260px !important;
            width: 260px !important;
        }
        [data-testid="collapsedControl"],
        button[kind="header"],
        section[data-testid="stSidebar"] button[title="Close sidebar"] {
            display: none !important;
            visibility: hidden !important;
        }
        section[data-testid="stSidebar"][aria-expanded="false"] {
            display: block !important;
            transform: none !important;
            margin-left: 0 !important;
        }
        section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
            padding: .3rem .7rem .85rem .7rem !important;
            margin-top: 0 !important;
        }
        [data-testid="stSidebarContent"],
        section[data-testid="stSidebar"] > div {
            padding-top: 0 !important;
            margin-top: 0 !important;
        }
        .main .block-container {
            padding-top: .15rem !important;
            padding-left: .8rem !important;
            padding-right: .8rem !important;
            padding-bottom: 1rem;
            max-width: none;
        }
        h1, h2, h3 { color: var(--jozani-text); letter-spacing: 0; }
        h3 { font-size: 1rem !important; margin: .35rem 0 .4rem 0 !important; }
        .brand-block {
            background: var(--jozani-crimson);
            color: #ffffff;
            border-radius: 0;
            padding: .9rem .85rem;
            margin: 0 0 .55rem 0;
        }
        .brand-title { font-size: 1.25rem; font-weight: 850; letter-spacing: .03rem; }
        .brand-subtitle { font-size: .76rem; opacity: .92; line-height: 1.35; margin-top: .35rem; }
        .sidebar-footer {
            position: fixed;
            bottom: .8rem;
            left: .9rem;
            width: 220px;
            border-top: 1px solid #eef0f4;
            padding-top: .8rem;
            color: #8f1027;
            font-size: .72rem;
            line-height: 1.35;
        }
        .coastal-strip {
            height: 82px;
            border-radius: 8px;
            margin-bottom: .65rem;
            background:
              linear-gradient(180deg, rgba(255,255,255,.15), rgba(255,255,255,.95)),
              linear-gradient(135deg, #bfe7f3 0%, #eaf8fc 42%, #f7e4b0 43%, #fff6da 100%);
            border: 1px solid #eef0f4;
        }
        div[role="radiogroup"] label {
            border-radius: 8px;
            padding: .18rem .45rem;
            margin-bottom: .15rem;
        }
        div[role="radiogroup"] label p {
            font-size: .82rem;
            font-weight: 650;
        }
        div[role="radiogroup"] label:has(input:checked) {
            background: var(--jozani-crimson);
            color: #ffffff;
        }
        .jozani-title {
            color: var(--jozani-text);
            font-size: 1.42rem;
            font-weight: 780;
            letter-spacing: 0;
            margin-bottom: .12rem;
        }
        .jozani-subtitle {
            color: #334155;
            font-size: .83rem;
            font-weight: 500;
            margin-top: .1rem;
            margin-bottom: .1rem;
        }
        .top-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 1rem;
            margin-top: 0;
            margin-bottom: .35rem;
        }
        .header-right {
            text-align: right;
            min-width: 250px;
        }
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid var(--jozani-border);
            border-radius: 8px;
            padding: .72rem .78rem;
            box-shadow: 0 1px 2px rgba(15, 23, 42, .04);
        }
        div[data-testid="stMetricLabel"] p { color: #64748b; font-weight: 700; font-size: .78rem; }
        div[data-testid="stMetricValue"] { color: var(--jozani-text); font-size: 1.55rem; font-weight: 850; }
        .kpi-card {
            background: #ffffff;
            border: 1px solid var(--jozani-border);
            border-radius: 8px;
            padding: .78rem .82rem;
            height: 128px;
            margin-bottom: .72rem;
            box-shadow: 0 2px 8px rgba(15, 23, 42, .035);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            overflow: hidden;
        }
        .kpi-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            border-radius: 8px;
            background: #f9e8ec;
            color: var(--jozani-crimson);
            margin-bottom: .35rem;
        }
        .kpi-icon svg { width: 16px; height: 16px; stroke-width: 2.2; }
        .kpi-label { color: #667085; font-size: .75rem; font-weight: 760; white-space: nowrap; }
        .kpi-value { color: var(--jozani-text); font-size: 1.55rem; line-height: 1.06; font-weight: 880; margin-top: .08rem; }
        .kpi-value.time-value { font-size: 1rem; line-height: 1.2; }
        .kpi-note { color: #64748b; font-size: .72rem; margin-top: .25rem; }
        .kpi-row-spacer { height: .25rem; }
        .section-card {
            background: #ffffff;
            border: 1px solid var(--jozani-border);
            border-radius: 8px;
            padding: .78rem .85rem;
            margin-bottom: .65rem;
            box-shadow: 0 2px 8px rgba(15, 23, 42, .035);
        }
        .section-title { display: flex; align-items: center; gap: .45rem; color: var(--jozani-text); font-size: .96rem; font-weight: 850; margin-bottom: .05rem; }
        .section-caption { color: #64748b; font-size: .72rem; margin-bottom: .48rem; }
        .connection-pill {
            display: inline-flex;
            align-items: center;
            gap: .45rem;
            color: #14532d;
            background: #ecfdf5;
            border: 1px solid #bbf7d0;
            border-radius: 999px;
            padding: .25rem .75rem;
            font-size: .82rem;
            font-weight: 750;
        }
        .connection-pill.error {
            color: #7f1d1d;
            background: #fef2f2;
            border-color: #fecaca;
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
        .coverage-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .58rem; }
        .coverage-card {
            border: 1px solid #eef0f4;
            border-radius: 8px;
            padding: .65rem;
            background: #fbfcfe;
        }
        .coverage-heading {
            display: flex;
            align-items: center;
            gap: .45rem;
            font-weight: 850;
            color: #172033;
            margin-bottom: .42rem;
        }
        .source-mark {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 24px;
            height: 24px;
            border-radius: 7px;
            color: white;
            font-weight: 900;
            font-size: .78rem;
        }
        .source-mark.booking { background: #2563eb; }
        .source-mark.tripadvisor { background: #15803d; }
        .coverage-row {
            display: flex;
            justify-content: space-between;
            border-top: 1px solid #eef0f4;
            padding: .29rem 0;
            font-size: .78rem;
        }
        .coverage-row span:first-child { color: #334155; font-weight: 650; }
        .coverage-row span:last-child { color: var(--jozani-crimson); font-weight: 850; }
        .section-note { color: var(--jozani-muted); font-size: .9rem; margin-top: -.35rem; }
        .soft-panel {
            border: 1px solid var(--jozani-border);
            border-radius: 8px;
            padding: 1rem;
            background: #ffffff;
        }
        .review-card {
            background: #ffffff;
            border: 1px solid var(--jozani-border);
            border-left: 4px solid var(--jozani-crimson);
            border-radius: 8px;
            padding: .95rem 1rem;
            margin-bottom: .75rem;
        }
        .review-meta {
            color: #64748b;
            font-size: .86rem;
            margin-bottom: .35rem;
        }
        .review-title {
            color: var(--jozani-text);
            font-weight: 760;
            margin-bottom: .25rem;
        }
        .review-text { color: #334155; line-height: 1.45; }
        .story-line {
            background: #fff;
            border: 1px solid var(--jozani-border);
            border-radius: 8px;
            padding: .85rem;
            color: #334155;
            font-weight: 700;
            text-align: center;
            margin-bottom: .9rem;
        }
        div[data-testid="stVerticalBlock"] { gap: .62rem; }
        div[data-testid="column"] > div[data-testid="stVerticalBlock"] { gap: .48rem; }
        div[data-testid="stHorizontalBlock"] { gap: .75rem; }
        .js-plotly-plot .modebar { display: none !important; }
        .stButton > button {
            border-radius: 8px;
            border: 1px solid var(--jozani-border);
        }
        .stTabs [data-baseweb="tab-list"] { gap: .35rem; }
        .stTabs [data-baseweb="tab"] {
            background: #ffffff;
            border: 1px solid var(--jozani-border);
            border-radius: 8px;
            padding: .45rem .8rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def title() -> None:
    st.markdown(
        """
        <div class="top-header">
            <div>
                <div class="jozani-title">Tourism Data Acquisition & Monitoring</div>
                <div class="jozani-subtitle">Live monitoring of multi-source tourism data collected for the Zanzibar Tourism Intelligence Platform.</div>
            </div>
        </div>
        """,
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


def percent_text(numerator: Any, denominator: Any) -> str:
    try:
        denominator = float(denominator or 0)
        numerator = float(numerator or 0)
    except (TypeError, ValueError):
        return "0%"
    if denominator <= 0:
        return "0%"
    return f"{(numerator / denominator) * 100:.1f}%"


def warn_section(title_text: str, error: Exception) -> None:
    print(f"[dashboard] {title_text} failed: {error}")
    st.warning(f"{title_text} unavailable.")
