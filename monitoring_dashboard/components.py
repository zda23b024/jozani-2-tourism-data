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
        html, body, .stApp {
            background: var(--jozani-bg);
            color: var(--jozani-text);
            font-family: Inter, "Segoe UI", Roboto, Arial, sans-serif;
            min-height: 100vh;
        }
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
        [data-testid="stSkillsNudgeAnchor"],
        [data-testid="stSkillsNudge"],
        div[role="status"][aria-live="polite"] {
            display: none !important;
            visibility: hidden !important;
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
            padding-top: 0 !important;
            padding-left: .95rem !important;
            padding-right: .95rem !important;
            padding-bottom: .6rem !important;
            max-width: none !important;
        }
        div[data-testid="stAppViewBlockContainer"] {
            padding-top: 0 !important;
            max-width: none !important;
        }
        .block-container {
            padding-top: 0 !important;
            margin-top: 0 !important;
        }
        section[data-testid="stSidebar"] {
            background: #ffffff;
            border-right: 1px solid var(--jozani-border);
            box-shadow: 4px 0 18px rgba(15, 23, 42, .04);
            min-width: 235px !important;
            width: 235px !important;
            max-width: 235px !important;
            height: 100vh !important;
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
            padding: 0 .55rem .65rem .55rem !important;
            margin-top: 0 !important;
        }
        [data-testid="stSidebarContent"],
        section[data-testid="stSidebar"] > div {
            padding-top: 0 !important;
            margin-top: 0 !important;
        }
        .main .block-container {
            padding-top: 0 !important;
            padding-left: .95rem !important;
            padding-right: .95rem !important;
            padding-bottom: .6rem;
            max-width: none;
        }
        h1, h2, h3 { color: var(--jozani-text); letter-spacing: 0; }
        h3 { font-size: 1rem !important; margin: .35rem 0 .4rem 0 !important; }
        .brand-block {
            background: var(--jozani-crimson);
            color: #ffffff;
            border-radius: 0 0 28px 0;
            padding: 1.05rem .9rem 1.15rem .9rem;
            margin: 0 -.55rem .55rem -.55rem;
        }
        .brand-title { font-size: 1.38rem; font-weight: 850; letter-spacing: .03rem; }
        .brand-subtitle { font-size: .78rem; opacity: .92; line-height: 1.35; margin-top: .38rem; }
        .sidebar-footer {
            position: fixed;
            bottom: 0;
            left: .55rem;
            width: 214px;
            border-top: 1px solid #eef0f4;
            padding-top: .72rem;
            color: #8f1027;
            font-size: .72rem;
            line-height: 1.35;
            background: #ffffff;
        }
        .coastal-strip {
            height: 104px;
            border-radius: 0;
            margin: .55rem -.55rem 0 -.55rem;
            background:
              radial-gradient(circle at 55% 25%, #244b23 0 9%, transparent 10%),
              radial-gradient(circle at 43% 32%, #386c34 0 11%, transparent 12%),
              radial-gradient(circle at 50% 56%, #e9d0a0 0 17%, transparent 18%),
              linear-gradient(180deg, #c9edf7 0%, #e9fbff 42%, #21b6c8 43%, #2cb8c6 64%, #f7e1ae 65%, #fff4d6 100%);
            border-top: 1px solid #eef0f4;
        }
        div[role="radiogroup"] label {
            border-radius: 8px;
            padding: .2rem .48rem;
            margin-bottom: .1rem;
            min-height: 34px;
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
            margin-top: .1rem;
            margin-bottom: .42rem;
            padding-left: .4rem;
            border-left: 5px solid var(--jozani-crimson);
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
            padding: .68rem .76rem;
            height: 116px;
            margin-bottom: .46rem;
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
            margin-bottom: .28rem;
        }
        .kpi-icon svg { width: 16px; height: 16px; stroke-width: 2.2; }
        .kpi-label { color: #667085; font-size: .72rem; font-weight: 760; white-space: nowrap; }
        .kpi-value { color: var(--jozani-text); font-size: 1.45rem; line-height: 1.04; font-weight: 880; margin-top: .08rem; }
        .kpi-value.time-value { font-size: .95rem; line-height: 1.16; }
        .kpi-note { color: #64748b; font-size: .68rem; margin-top: .2rem; }
        .kpi-row-spacer { height: .08rem; }
        .section-card {
            background: #ffffff;
            border: 1px solid var(--jozani-border);
            border-radius: 8px;
            padding: .72rem .78rem;
            margin-bottom: .48rem;
            box-shadow: 0 2px 8px rgba(15, 23, 42, .035);
        }
        .section-title {
            display: flex;
            align-items: center;
            gap: .45rem;
            color: var(--jozani-text);
            font-size: .94rem;
            font-weight: 850;
            margin-bottom: .05rem;
            border-left: 4px solid var(--jozani-crimson);
            padding-left: .42rem;
        }
        .section-caption { color: #64748b; font-size: .7rem; margin-bottom: .4rem; }
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
        .coverage-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .56rem; }
        .coverage-card {
            border: 1px solid #eef0f4;
            border-radius: 8px;
            padding: .58rem;
            background: #fbfcfe;
            min-height: 168px;
        }
        .coverage-heading {
            display: flex;
            align-items: center;
            gap: .45rem;
            font-weight: 850;
            color: #172033;
            margin-bottom: .36rem;
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
            padding: .25rem 0;
            font-size: .76rem;
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
        div[data-testid="stVerticalBlock"] { gap: .46rem; }
        div[data-testid="column"] > div[data-testid="stVerticalBlock"] { gap: .32rem; }
        div[data-testid="stHorizontalBlock"] { gap: .72rem; }
        .plot-card {
            margin-bottom: -.32rem;
            padding: .72rem .78rem 0 .78rem;
            background: #ffffff;
            border: 1px solid var(--jozani-border);
            border-bottom: 0;
            border-radius: 8px 8px 0 0;
            box-shadow: 0 2px 8px rgba(15, 23, 42, .035);
        }
        div[data-testid="stPlotlyChart"] {
            background: #ffffff;
            border: 1px solid var(--jozani-border);
            border-top: 0;
            border-radius: 0 0 8px 8px;
            padding: .12rem .45rem .35rem .45rem;
            margin-bottom: .48rem;
            box-shadow: 0 2px 8px rgba(15, 23, 42, .035);
        }
        div[data-testid="stPlotlyChart"] > div {
            margin: 0 !important;
        }
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
