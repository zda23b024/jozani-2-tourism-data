from __future__ import annotations

import os

import plotly.express as px
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from components import (
    dataframe_or_empty,
    elapsed_from,
    format_int,
    format_time,
    inject_css,
    status_badge,
    title,
    warn_section,
)
from db import refresh_seconds
from queries import (
    Filters,
    data_quality,
    database_growth,
    database_size,
    filter_options,
    kpis,
    latest_run,
    latest_runs,
    places_by_category,
    rating_distribution_by_source,
    review_languages,
    reviews_by_source,
    reviews_over_time,
    source_overview,
    top_reviewed_places,
)
from utils import clean_numeric_columns, normalize_display_frame


st.set_page_config(
    page_title="Jozani 2.0 Monitor",
    layout="wide",
)

REFRESH_SECONDS = refresh_seconds()
CHART_COLORS = ["#0f766e", "#2563eb", "#d97706", "#7c3aed", "#475569"]


@st.cache_data(ttl=REFRESH_SECONDS)
def load_data(filters: Filters) -> dict:
    return {
        "filter_options": filter_options(),
        "kpis": kpis(filters),
        "source_overview": source_overview(),
        "latest_run": latest_run(),
        "reviews_over_time": reviews_over_time(filters.review_period_days),
        "reviews_by_source": reviews_by_source(),
        "places_by_category": places_by_category(filters),
        "top_reviewed_places": top_reviewed_places(filters),
        "rating_distribution": rating_distribution_by_source(),
        "review_languages": review_languages(),
        "latest_runs": latest_runs(filters),
        "data_quality": data_quality(),
        "database_growth": database_growth(),
        "database_size": database_size(),
    }


def sidebar_filters() -> Filters:
    try:
        options = filter_options()
    except Exception as error:
        print(f"[dashboard] filter loading failed: {error}")
        options = {"sources": ["All"], "categories": ["All"], "statuses": ["All"]}

    st.sidebar.header("Filters")
    source = st.sidebar.selectbox("Source", options["sources"])
    category = st.sidebar.selectbox("Category", options["categories"])
    status = st.sidebar.selectbox("Run status", options["statuses"])
    period_label = st.sidebar.selectbox(
        "Review collection period",
        ["Last 30 days", "Last 7 days", "All time"],
    )
    period_days = {
        "Last 7 days": 7,
        "Last 30 days": 30,
        "All time": None,
    }[period_label]
    if st.sidebar.button("Refresh now"):
        st.cache_data.clear()
        st.rerun()
    st.sidebar.caption(f"Auto refresh: every {REFRESH_SECONDS} seconds")
    return Filters(
        source=source,
        category=category,
        run_status=status,
        review_period_days=period_days,
    )


def render_kpis(data: dict) -> None:
    values = data["kpis"]
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Places", format_int(values.get("total_places")))
    col2.metric("Total Reviews", format_int(values.get("total_reviews")))
    col3.metric("Sources", format_int(values.get("total_sources")))
    col4.metric("Running Jobs", format_int(values.get("active_jobs")))
    col5.metric("Last Data Update", format_time(values.get("last_data_update")))


def render_current_status(run: dict) -> None:
    st.subheader("Current Collection Status")
    if not run:
        st.info("No scraping runs recorded yet. Progress unavailable.")
        return

    cols = st.columns([1.2, 1, 1, 1, 1])
    cols[0].markdown(status_badge(run.get("status")), unsafe_allow_html=True)
    cols[1].metric("Source", run.get("source_code") or "-")
    cols[2].metric("Entity", run.get("entity_type") or "-")
    cols[3].metric("Records Found", format_int(run.get("records_found")))
    cols[4].metric("Elapsed", elapsed_from(run.get("started_at"), run.get("completed_at")))

    pages_total = run.get("pages_total")
    pages_success = run.get("pages_successful")
    if pages_total and pages_success is not None:
        st.progress(min(1.0, float(pages_success) / float(pages_total)))
    else:
        st.caption("Progress unavailable")

    if run.get("stop_reason"):
        st.caption(f"Stop reason: {run.get('stop_reason')}")


def render_source_overview(frame) -> None:
    st.subheader("Source Overview")
    if frame.empty:
        st.info("No source statistics yet.")
        return
    frame = normalize_display_frame(frame)
    st.dataframe(frame, use_container_width=True, hide_index=True)


def render_charts(data: dict) -> None:
    left, right = st.columns(2)

    with left:
        st.subheader("Reviews Collected Over Time")
        frame = clean_numeric_columns(data["reviews_over_time"], ["reviews_collected"])
        if frame.empty:
            st.info("No review collection trend yet.")
        else:
            st.plotly_chart(
                px.line(
                    frame,
                    x="collection_day",
                    y="reviews_collected",
                    markers=True,
                    color_discrete_sequence=CHART_COLORS,
                    labels={
                        "collection_day": "Collection day",
                        "reviews_collected": "Reviews collected",
                    },
                ),
                use_container_width=True,
            )

    with right:
        st.subheader("Reviews By Source")
        frame = clean_numeric_columns(data["reviews_by_source"], ["reviews"])
        if frame.empty or frame["reviews"].sum() == 0:
            st.info("No reviews by source yet.")
        else:
            st.plotly_chart(
                px.bar(
                    frame,
                    x="source_code",
                    y="reviews",
                    labels={"source_code": "Source"},
                    color_discrete_sequence=CHART_COLORS,
                ),
                use_container_width=True,
            )

    left, right = st.columns(2)
    with left:
        st.subheader("Canonical Places By Category")
        frame = clean_numeric_columns(data["places_by_category"], ["canonical_places"])
        if frame.empty or frame["canonical_places"].sum() == 0:
            st.info("No category distribution yet.")
        else:
            st.plotly_chart(
                px.bar(
                    frame,
                    x="category",
                    y="canonical_places",
                    color_discrete_sequence=CHART_COLORS,
                ),
                use_container_width=True,
            )

    with right:
        st.subheader("Rating Distribution")
        st.caption("Normalized to 5-point scale for comparison.")
        frame = clean_numeric_columns(data["rating_distribution"], ["reviews"])
        if frame.empty or frame["reviews"].sum() == 0:
            st.info("No rating distribution yet.")
        else:
            st.plotly_chart(
                px.bar(
                    frame,
                    x="normalized_rating_5",
                    y="reviews",
                    color="source_code",
                    barmode="group",
                    color_discrete_sequence=CHART_COLORS,
                    labels={"normalized_rating_5": "Rating"},
                ),
                use_container_width=True,
            )

    left, right = st.columns(2)
    with left:
        st.subheader("Database Growth")
        frame = clean_numeric_columns(data["database_growth"], ["places_added", "reviews_added"])
        if frame.empty:
            st.info("No growth trend yet.")
        else:
            st.plotly_chart(
                px.line(
                    frame,
                    x="day",
                    y=["places_added", "reviews_added"],
                    markers=True,
                    color_discrete_sequence=CHART_COLORS,
                ),
                use_container_width=True,
            )

    with right:
        st.subheader("Review Languages")
        frame = clean_numeric_columns(data["review_languages"], ["reviews"])
        if frame.empty or frame["reviews"].sum() == 0:
            st.info("Language data unavailable.")
        else:
            st.plotly_chart(
                px.bar(
                    frame,
                    x="language",
                    y="reviews",
                    color_discrete_sequence=CHART_COLORS,
                ),
                use_container_width=True,
            )


def render_tables(data: dict) -> None:
    left, right = st.columns(2)
    with left:
        st.subheader("Top Source Listings By Review Count")
        dataframe_or_empty(
            normalize_display_frame(data["top_reviewed_places"]),
            "No reviewed listings yet.",
        )
    with right:
        st.subheader("Data Quality")
        dataframe_or_empty(
            normalize_display_frame(data["data_quality"]),
            "No data-quality metrics yet.",
        )

    st.subheader("Latest Scraping Runs")
    dataframe_or_empty(
        normalize_display_frame(data["latest_runs"]),
        "No scraping run history yet.",
    )


def render_database_size(data: dict) -> None:
    st.subheader("Database Size")
    values = data.get("database_size") or {}
    if not values:
        st.info("Database size information unavailable.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Database", values.get("database_size", "-"))
    c2.metric("Reviews", values.get("reviews_table_size", "-"))
    c3.metric("Places", values.get("places_table_size", "-"))
    c4.metric("Source Records", values.get("source_records_table_size", "-"))


def main() -> None:
    st_autorefresh(interval=REFRESH_SECONDS * 1000, key="jozani_monitor_refresh")
    inject_css()
    title()

    filters = sidebar_filters()

    try:
        data = load_data(filters)
    except Exception as error:
        print(f"[dashboard] database unavailable: {error}")
        st.error("Database unavailable. The dashboard will recover when PostgreSQL is reachable.")
        return

    try:
        render_kpis(data)
    except Exception as error:
        warn_section("KPI cards", error)

    try:
        render_current_status(data["latest_run"])
    except Exception as error:
        warn_section("Current collection status", error)

    try:
        render_source_overview(data["source_overview"])
    except Exception as error:
        warn_section("Source overview", error)

    try:
        render_charts(data)
    except Exception as error:
        warn_section("Charts", error)

    try:
        render_tables(data)
    except Exception as error:
        warn_section("Tables", error)

    try:
        render_database_size(data)
    except Exception as error:
        warn_section("Database size", error)

    st.caption("Read-only monitor. This dashboard does not start, stop, or modify scraper runs.")


if __name__ == "__main__":
    main()
