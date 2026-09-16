from __future__ import annotations

import math
from html import escape
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from components import (
    dataframe_or_empty,
    duration_text,
    format_int,
    format_time,
    inject_css,
    percent_text,
    status_badge,
    warn_section,
)
from db import refresh_seconds
from queries import (
    Filters,
    collection_status_by_source,
    collection_health,
    connection_status,
    data_quality,
    database_size,
    database_summary,
    entity_counts,
    explorer_count,
    explorer_places,
    filter_options,
    health_summary,
    overview_kpis,
    places_by_source_category,
    recent_runs,
    review_language_options,
    review_metrics,
    reviews_over_time,
    sample_reviews,
    sample_reviews_count,
    source_coverage,
    top_reviewed_places,
)
from utils import clean_numeric_columns, latest_log_status, normalize_display_frame


st.set_page_config(
    page_title="Jozani 2.0 Tourism Monitor",
    layout="wide",
    initial_sidebar_state="expanded",
)

REFRESH_SECONDS = refresh_seconds()
SOURCE_COLORS = {
    "Booking.com": "#C58B22",
    "BOOKING": "#C58B22",
    "Tripadvisor": "#9F1239",
    "TRIPADVISOR": "#9F1239",
}
CHART_COLORS = ["#9F1239", "#C58B22", "#15803D", "#2563EB", "#667085"]
PAGE_SIZE_OPTIONS = [25, 50, 100, 200]


@st.cache_data(ttl=REFRESH_SECONDS)
def load_options() -> dict[str, list[str]]:
    return filter_options()


@st.cache_data(ttl=REFRESH_SECONDS)
def load_connection_status() -> dict:
    return connection_status()


@st.cache_data(ttl=REFRESH_SECONDS)
def load_overview(filters: Filters) -> dict[str, Any]:
    return {
        "kpis": overview_kpis(filters),
        "coverage": source_coverage(),
        "places_by_source_category": places_by_source_category(filters),
        "reviews_over_time": reviews_over_time(filters.review_period_days),
        "top_reviewed_places": top_reviewed_places(filters),
        "recent_runs": recent_runs(),
    }


@st.cache_data(ttl=REFRESH_SECONDS)
def load_explorer(source: str, category: str, search: str, limit: int, page: int) -> dict[str, Any]:
    offset = max(page - 1, 0) * limit
    return {
        "count": explorer_count(source, category, search),
        "places": explorer_places(source, category, search, limit, offset),
    }


@st.cache_data(ttl=REFRESH_SECONDS)
def load_review_page(
    source: str,
    category: str,
    search: str,
    language: str,
    rating_min: float,
    rating_max: float,
    limit: int,
    page: int,
) -> dict[str, Any]:
    offset = max(page - 1, 0) * limit
    return {
        "metrics": review_metrics(),
        "languages": review_language_options(),
        "count": sample_reviews_count(
            source=source,
            category=category,
            place_search=search,
            language=language,
            rating_min=rating_min,
            rating_max=rating_max,
        ),
        "reviews": sample_reviews(
            source=source,
            category=category,
            place_search=search,
            language=language,
            rating_min=rating_min,
            rating_max=rating_max,
            limit=limit,
            offset=offset,
        ),
    }


@st.cache_data(ttl=REFRESH_SECONDS)
def load_health(filters: Filters) -> dict[str, Any]:
    return {
        "summary": health_summary(),
        "source_status": collection_status_by_source(),
        "runs": collection_health(filters),
        "live_log": latest_log_status(),
    }


@st.cache_data(ttl=REFRESH_SECONDS)
def load_database_page() -> dict[str, Any]:
    return {
        "summary": database_summary(),
        "quality": data_quality(),
        "entities": entity_counts(),
        "size": database_size(),
    }


def _safe_frame(frame: pd.DataFrame, numeric_columns: list[str] | None = None) -> pd.DataFrame:
    frame = normalize_display_frame(frame)
    if numeric_columns:
        frame = clean_numeric_columns(frame, numeric_columns)
    return frame


def icon_svg(name: str) -> str:
    icons = {
        "pin": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 21s7-5.2 7-12a7 7 0 0 0-14 0c0 6.8 7 12 7 12Z"/><circle cx="12" cy="9" r="2.4"/></svg>',
        "review": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v7A2.5 2.5 0 0 1 17.5 15H9l-5 4V5.5Z"/><path d="M8 8h8M8 11h5"/></svg>',
        "database": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5"/><path d="M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></svg>',
        "calendar": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/><path d="M8 14h3M13 14h3M8 17h3"/></svg>',
        "shield": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 22s8-3.6 8-10V5l-8-3-8 3v7c0 6.4 8 10 8 10Z"/><path d="m8.5 12 2.2 2.2 4.8-5"/></svg>',
    }
    return icons[name]


def display_source(value: str) -> str:
    upper = str(value or "").upper()
    if upper == "BOOKING":
        return "Booking.com"
    if upper == "TRIPADVISOR":
        return "Tripadvisor"
    return str(value or "")


def compact_datetime(value: Any) -> str:
    if value is None or pd.isna(value):
        return "No data yet"
    if isinstance(value, str):
        try:
            value = pd.to_datetime(value)
        except Exception:
            return value[:16]
    return value.strftime("%d %b %Y<br/>%H:%M")


def sidebar() -> str:
    st.sidebar.markdown(
        """
        <div class="brand-block">
            <div class="brand-title">JOZANI 2.0</div>
            <div class="brand-subtitle">Zanzibar Tourism<br/>Intelligence Platform</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    labels = {
        "Overview": "⌂  Overview",
        "Data Explorer": "⌕  Data Explorer",
        "Reviews": "▱  Reviews",
        "Collection Health": "✦  Collection Health",
        "Database": "◎  Database",
    }
    labels = {key: key for key in labels}
    reverse_labels = {value: key for key, value in labels.items()}
    page = st.sidebar.radio(
        "Page",
        list(labels.values()),
        label_visibility="collapsed",
    )
    st.sidebar.markdown(
        """
        <div class="sidebar-footer">
            <div class="coastal-strip"></div>
            <div style="font-family: Georgia, serif; font-style: italic; color:#b7791f;">Zanzibar<br/>for a sustainable tomorrow</div>
            <div style="margin-top:.55rem; color:#8f1027; font-weight:800;">IIT MADRAS | GITAA</div>
            <div style="color:#64748b;">Industrial Internship Project</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    return reverse_labels[page]


def render_header(status: dict | None, connected: bool = True) -> None:
    if connected and status:
        indicator = '<span class="connection-pill">PostgreSQL Connected</span>'
        checked = format_time(status.get("checked_at"))
    else:
        indicator = '<span class="connection-pill error">Database unavailable</span>'
        checked = "Unable to retrieve monitoring data"
    st.markdown(
        f"""
        <div class="top-header">
            <div>
                <div class="jozani-title">Tourism Data Acquisition &amp; Monitoring</div>
                <div class="jozani-subtitle">Live monitoring of multi-source tourism data collected for the Zanzibar Tourism Intelligence Platform.</div>
            </div>
            <div class="header-right">
                {indicator}
                <div class="section-note" style="margin-top:.35rem;">Last updated: {checked}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_card(column, icon: str, label: str, value: str, note: str = "") -> None:
    value_class = "kpi-value time-value" if "<br/>" in value else "kpi-value"
    column.markdown(
        f"""
        <div class="kpi-card">
            <div>
                <div class="kpi-icon">{icon}</div>
                <div class="kpi-label">{label}</div>
                <div class="{value_class}">{value}</div>
            </div>
            <div class="kpi-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_row(kpis: dict) -> None:
    total_reviews = kpis.get("total_reviews") or 0
    cols = st.columns(5, gap="small")
    render_kpi_card(cols[0], icon_svg("pin"), "Unique Tourism Places", format_int(kpis.get("canonical_places")), "Canonical places")
    render_kpi_card(cols[1], icon_svg("review"), "Total Reviews", format_int(total_reviews), "Stored review corpus")
    render_kpi_card(cols[2], icon_svg("database"), "Data Sources", format_int(kpis.get("active_sources")), "Populated platforms")
    render_kpi_card(cols[3], icon_svg("calendar"), "Last Collection", compact_datetime(kpis.get("last_successful_collection")), "Latest successful run")
    render_kpi_card(cols[4], icon_svg("shield"), "Review Text Coverage", percent_text(kpis.get("reviews_with_text"), total_reviews), "Reviews with text")


def render_source_coverage(frame: pd.DataFrame) -> None:
    frame = _safe_frame(frame, ["accommodations_hotels", "attractions", "restaurants", "reviews"])
    by_source = {str(row.get("source", "")).upper(): row for _, row in frame.iterrows()}

    def value(source: str, key: str) -> str:
        row = by_source.get(source.upper())
        if row is None:
            return "0"
        return format_int(row.get(key))

    st.markdown(
        f"""
        <div class="section-card">
            <div class="section-title">Source Coverage</div>
            <div class="section-caption">Tourism places and reviews collected from each source and category.</div>
            <div class="coverage-grid">
                <div class="coverage-card">
                    <div class="coverage-heading"><span class="source-mark booking">B</span>Booking.com</div>
                    <div class="coverage-row"><span>Accommodations</span><span>{value("BOOKING", "accommodations_hotels")}</span></div>
                    <div class="coverage-row"><span>Attractions</span><span>{value("BOOKING", "attractions")}</span></div>
                    <div class="coverage-row"><span>Reviews</span><span>{value("BOOKING", "reviews")}</span></div>
                </div>
                <div class="coverage-card">
                    <div class="coverage-heading"><span class="source-mark tripadvisor">T</span>Tripadvisor</div>
                    <div class="coverage-row"><span>Hotels</span><span>{value("TRIPADVISOR", "accommodations_hotels")}</span></div>
                    <div class="coverage-row"><span>Attractions</span><span>{value("TRIPADVISOR", "attractions")}</span></div>
                    <div class="coverage-row"><span>Restaurants</span><span>{value("TRIPADVISOR", "restaurants")}</span></div>
                    <div class="coverage-row"><span>Reviews</span><span>{value("TRIPADVISOR", "reviews")}</span></div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_overview(filters: Filters) -> None:
    data = load_overview(filters)
    render_kpi_row(data["kpis"])
    st.markdown('<div class="kpi-row-spacer"></div>', unsafe_allow_html=True)

    left, right = st.columns(2, gap="small")
    with left:
        render_source_coverage(data["coverage"])
    with right:
        st.markdown('<div class="plot-card"><div class="section-title">Places by Source and Category</div><div class="section-caption">Number of tourism places collected from each source.</div></div>', unsafe_allow_html=True)
        frame = _safe_frame(data["places_by_source_category"], ["source_records", "canonical_places"])
        if frame.empty:
            st.info("No place records available for the selected filters.")
        else:
            frame = frame.copy()
            frame["source"] = frame["source"].apply(display_source)
            fig = px.bar(
                frame,
                x="category",
                y="source_records",
                color="source",
                barmode="group",
                text="source_records",
                color_discrete_map=SOURCE_COLORS,
                labels={
                    "category": "Category",
                    "source_records": "Count",
                    "source": "Source",
                },
            )
            fig.update_traces(hovertemplate="Source=%{fullData.name}<br>Category=%{x}<br>Count=%{y}<extra></extra>")
            fig.update_traces(texttemplate="%{text:,}", textposition="outside", cliponaxis=False)
            fig.update_layout(
                height=218,
                legend_title_text="",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=8, r=8, t=24, b=4),
                plot_bgcolor="#ffffff",
                paper_bgcolor="#ffffff",
                yaxis=dict(gridcolor="#EEF2F6", title=None),
                xaxis=dict(title=None),
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.markdown('<div class="plot-card"><div class="section-title">Reviews Collected Over Time</div><div class="section-caption">Daily count of reviews collected from each source.</div></div>', unsafe_allow_html=True)
    frame = _safe_frame(data["reviews_over_time"], ["reviews_collected"])
    if frame.empty:
        st.info("No review collection trend is available for this period.")
    else:
        fig = px.line(
            frame,
            x="collection_day",
            y="reviews_collected",
            markers=True,
            color_discrete_sequence=[CHART_COLORS[0]],
            labels={"collection_day": "Collection day", "reviews_collected": "Reviews collected"},
        )
        fig.update_traces(line=dict(width=2.5, color="#9F1239"), marker=dict(size=5))
        fig.update_layout(
            height=188,
            showlegend=False,
            margin=dict(l=8, r=8, t=12, b=4),
            plot_bgcolor="#ffffff",
            paper_bgcolor="#ffffff",
            yaxis=dict(gridcolor="#EEF2F6", title=None),
            xaxis=dict(title=None),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.markdown('<div class="section-title">Top 10 Most Reviewed Tourism Places</div><div class="section-caption">Ranked by actual stored review rows in PostgreSQL.</div>', unsafe_allow_html=True)
    top = _safe_frame(data["top_reviewed_places"], ["#", "Stored Reviews"])
    if not top.empty and "Source" in top.columns:
        top["Source"] = top["Source"].apply(display_source)
    dataframe_or_empty(top, "No reviewed places found for the selected filters.")

    st.markdown('<div class="section-title">Recent Collection Runs</div><div class="section-caption">Latest data collection runs from all sources.</div>', unsafe_allow_html=True)
    runs = normalize_display_frame(data["recent_runs"])
    if not runs.empty and "status" in runs.columns:
        runs["status"] = runs["status"].apply(lambda value: str(value).upper())
    if not runs.empty and "source" in runs.columns:
        runs["source"] = runs["source"].apply(display_source)
    dataframe_or_empty(runs, "No recent collection runs recorded.")


def render_data_explorer(filters: Filters) -> None:
    st.subheader("Data Explorer")
    options = load_options()
    col1, col2, col3, col4, col5 = st.columns([1, 1, 1.4, .9, .8])
    source = col1.selectbox("Source", options["sources"], key="explorer_source")
    category = col2.selectbox("Category", options["categories"], key="explorer_category")
    search = col3.text_input("Place search", "", key="explorer_search")
    limit = col4.selectbox("Rows per page", PAGE_SIZE_OPTIONS, index=1, key="explorer_limit")

    count = explorer_count(source, category, search)
    total = int(count.get("records") or 0)
    total_pages = max(1, math.ceil(total / limit))
    page = col5.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1, key="explorer_page")

    data = load_explorer(source, category, search, limit, page)
    total = int(data["count"].get("records") or 0)
    st.caption(f"Showing page {page} of {max(1, math.ceil(total / limit))} | {format_int(total)} source records")
    frame = _safe_frame(data["places"], ["rating", "review_count"])
    dataframe_or_empty(frame, "No places match the selected filters.")


def render_reviews(filters: Filters) -> None:
    st.subheader("Reviews")
    st.markdown(
        '<div class="story-line">Tourism Platform -> Review Collection -> PostgreSQL -> Structured Review Corpus -> Future Sentiment / Aspect / Topic Analysis</div>',
        unsafe_allow_html=True,
    )
    options = load_options()
    languages = review_language_options()
    c1, c2, c3, c4, c5 = st.columns([1, 1, 1.2, 1, .9])
    source = c1.selectbox("Source", options["sources"], key="review_source")
    category = c2.selectbox("Category", options["categories"], key="review_category")
    place_search = c3.text_input("Place", "", key="review_place")
    language = c4.selectbox("Language", languages, key="review_language")
    limit = c5.selectbox("Reviews per page", [10, 25, 50, 100], index=1, key="review_limit")
    rating_min, rating_max = st.slider("Rating range", 0.0, 10.0, (0.0, 10.0), 0.5)

    count = sample_reviews_count(source, category, place_search, language, rating_min, rating_max)
    total_matching = int(count.get("records") or 0)
    total_pages = max(1, math.ceil(total_matching / limit))
    page = st.number_input("Review page", min_value=1, max_value=total_pages, value=1, step=1)

    data = load_review_page(
        source,
        category,
        place_search,
        language,
        rating_min,
        rating_max,
        limit,
        page,
    )
    metrics = data["metrics"]
    total_reviews = metrics.get("total_reviews") or 0
    cols = st.columns(5)
    cols[0].metric("Total Reviews", format_int(total_reviews))
    cols[1].metric("Reviews With Text", format_int(metrics.get("reviews_with_text")))
    cols[2].metric("Languages", format_int(metrics.get("languages")))
    cols[3].metric("Reviewers", format_int(metrics.get("reviewers")))
    cols[4].metric("Rating Coverage", percent_text(metrics.get("reviews_with_rating"), total_reviews))
    st.caption(f"Showing page {page} of {total_pages} | {format_int(total_matching)} matching reviews")

    frame = normalize_display_frame(data["reviews"])
    if frame.empty:
        st.info("No reviews match the selected filters.")
        return

    for _, row in frame.iterrows():
        title_text = escape(str(row.get("review_title") or "").strip())
        review_text = escape(str(row.get("review_text") or "").strip())
        source = escape(str(row.get("source", "-")))
        category = escape(str(row.get("category", "-")))
        place = escape(str(row.get("place", "-")))
        language = escape(str(row.get("language", "-")))
        reviewer = escape(str(row.get("reviewer", "-")))
        rating = row.get("rating")
        rating_scale = row.get("rating_scale")
        rating_text = "-"
        if pd.notna(rating):
            rating_text = escape(f"{rating}")
            if pd.notna(rating_scale):
                rating_text = escape(f"{rating}/{rating_scale}")
        st.markdown(
            f"""
            <div class="review-card">
                <div class="review-meta">
                    {source} | {category} | {place}
                    | Rating: {rating_text} | Date: {format_time(row.get("review_date"))}
                    | Language: {language} | Reviewer: {reviewer}
                </div>
                <div class="review-title">{title_text or "Untitled review"}</div>
                <div class="review-text">{review_text or "No review text stored for this record."}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_live_log(status: dict) -> None:
    st.subheader("Live Log Monitor")
    if not status:
        st.info("No run logs found in the configured output/logs directory.")
        return
    cols = st.columns(5)
    cols[0].markdown(status_badge(status.get("status")), unsafe_allow_html=True)
    cols[1].metric("Source", status.get("source") or "-")
    cols[2].metric("Entity", status.get("entity") or "-")
    cols[3].metric("Unique Seen", format_int(status.get("total_unique") or status.get("latest_count")))
    cols[4].metric("Last Log Update", format_time(status.get("last_update")))
    st.caption(f"Log file: {status.get('log_file')} | Updated {status.get('seconds_since_update')} seconds ago")
    if status.get("detected_issue"):
        st.warning(status["detected_issue"])
    if status.get("last_message"):
        st.markdown(f'<div class="section-note">Latest: {status["last_message"]}</div>', unsafe_allow_html=True)
    if status.get("recent_lines"):
        with st.expander("Recent log lines"):
            st.code(status["recent_lines"], language="text")


def render_collection_health(filters: Filters) -> None:
    data = load_health(filters)
    summary = data["summary"]
    cols = st.columns(5)
    cols[0].metric("Last Successful Run", format_time(summary.get("last_successful_run")))
    cols[1].metric("Last Failed Run", format_time(summary.get("last_failed_run")))
    cols[2].metric("Successful Runs", format_int(summary.get("successful_runs")))
    cols[3].metric("Failed Runs", format_int(summary.get("failed_runs")))
    cols[4].metric("Running Jobs", format_int(summary.get("running_jobs")))

    render_live_log(data["live_log"])
    st.subheader("Collection Status by Source")
    dataframe_or_empty(normalize_display_frame(data["source_status"]), "No source status records found.")

    st.subheader("Scraping Run History")
    runs = normalize_display_frame(data["runs"])
    if runs.empty:
        st.info("No scraping run history found.")
        return
    runs = runs.copy()
    if "duration_seconds" in runs.columns:
        runs["duration"] = runs["duration_seconds"].apply(duration_text)
        runs = runs.drop(columns=["duration_seconds"])
    dataframe_or_empty(runs, "No scraping runs match the selected filters.")


def render_database() -> None:
    data = load_database_page()
    st.subheader("Database Status")
    summary = data["summary"]
    cols = st.columns(5)
    cols[0].metric("Sources", format_int(summary.get("sources")))
    cols[1].metric("Canonical Places", format_int(summary.get("canonical_places")))
    cols[2].metric("Source Records", format_int(summary.get("source_records")))
    cols[3].metric("Reviews", format_int(summary.get("reviews")))
    cols[4].metric("Reviewers", format_int(summary.get("reviewers")))

    cols = st.columns(4)
    cols[0].metric("Accommodations", format_int(summary.get("accommodations")))
    cols[1].metric("Attractions", format_int(summary.get("attractions")))
    cols[2].metric("Restaurants", format_int(summary.get("restaurants")))
    cols[3].metric("Latest DB Update", format_time(summary.get("latest_database_update")))

    size = data["size"]
    cols = st.columns(4)
    cols[0].metric("Database Size", size.get("database_size", "-"))
    cols[1].metric("Reviews Table", size.get("reviews_table_size", "-"))
    cols[2].metric("Places Table", size.get("places_table_size", "-"))
    cols[3].metric("Source Records Table", size.get("source_records_table_size", "-"))

    left, right = st.columns(2)
    with left:
        st.subheader("Entity Counts")
        dataframe_or_empty(normalize_display_frame(data["entities"]), "No entity counts available.")
    with right:
        st.subheader("Data Quality Indicators")
        dataframe_or_empty(normalize_display_frame(data["quality"]), "No quality indicators available.")


def main() -> None:
    st_autorefresh(interval=REFRESH_SECONDS * 1000, key="jozani_monitor_refresh")
    inject_css()
    page = sidebar()

    try:
        render_header(load_connection_status())
        filters = Filters()
    except Exception as error:
        print(f"[dashboard] database unavailable: {error}")
        render_header(None, connected=False)
        st.error("Database unavailable. Unable to retrieve monitoring data.")
        return

    try:
        if page == "Overview":
            render_overview(filters)
        elif page == "Data Explorer":
            render_data_explorer(filters)
        elif page == "Reviews":
            render_reviews(filters)
        elif page == "Collection Health":
            render_collection_health(filters)
        elif page == "Database":
            render_database()
    except Exception as error:
        warn_section(page, error)

    st.caption("Read-only monitor. This dashboard does not start, stop, or modify scraper jobs.")


if __name__ == "__main__":
    main()
