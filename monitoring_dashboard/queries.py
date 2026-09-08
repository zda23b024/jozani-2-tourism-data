from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from db import query_dataframe, query_one


RUNNING_STATUSES = ("running", "started", "collecting", "in_progress")


@dataclass(frozen=True)
class Filters:
    source: str = "All"
    category: str = "All"
    run_status: str = "All"
    review_period_days: int | None = 30


def _source_filter(source: str, alias: str = "s") -> tuple[str, list]:
    if source == "All":
        return "", []
    return f" AND {alias}.source_code = %s", [source]


def _category_filter(category: str, alias: str = "pt") -> tuple[str, list]:
    if category == "All":
        return "", []
    return f" AND {alias}.type_group = %s", [category]


def kpis(filters: Filters) -> dict:
    source_sql, source_params = _source_filter(filters.source)
    category_sql, category_params = _category_filter(filters.category)
    params = tuple(source_params + category_params)
    data = query_one(
        f"""
        SELECT
            COUNT(DISTINCT p.place_id)::bigint AS total_places,
            COUNT(DISTINCT r.review_id)::bigint AS total_reviews,
            COUNT(DISTINCT s.source_id)::bigint AS total_sources,
            COALESCE(MAX(GREATEST(
                COALESCE(psr.updated_at, 'epoch'::timestamptz),
                COALESCE(r.created_at, 'epoch'::timestamptz)
            )), NULL) AS last_data_update
        FROM places p
        JOIN place_types pt ON pt.place_type_id = p.place_type_id
        LEFT JOIN place_source_records psr ON psr.place_id = p.place_id
        LEFT JOIN sources s ON s.source_id = psr.source_id
        LEFT JOIN reviews r ON r.place_source_id = psr.place_source_id
        WHERE 1 = 1
          {source_sql}
          {category_sql}
        """,
        params,
    )
    running = query_one(
        """
        SELECT COUNT(*)::bigint AS active_jobs
        FROM scraping_runs
        WHERE LOWER(status) = ANY(%s)
          AND completed_at IS NULL
        """,
        (list(RUNNING_STATUSES),),
    )
    return {**data, **running}


def source_overview() -> pd.DataFrame:
    return query_dataframe(
        """
        SELECT
            s.source_code,
            s.source_name,
            COUNT(DISTINCT psr.place_source_id)::bigint AS source_listings,
            COUNT(DISTINCT p.place_id)::bigint AS canonical_places,
            COUNT(DISTINCT r.review_id)::bigint AS reviews,
            COUNT(DISTINCT psr.place_source_id) FILTER (WHERE pt.type_group = 'Accommodation')::bigint AS accommodations,
            COUNT(DISTINCT psr.place_source_id) FILTER (WHERE pt.type_group IN ('Attraction', 'Activity'))::bigint AS attractions,
            COUNT(DISTINCT psr.place_source_id) FILTER (WHERE pt.type_group = 'Restaurant')::bigint AS restaurants,
            ROUND(AVG(psr.review_score)::numeric, 2) AS average_rating,
            MAX(COALESCE(psr.last_scraped_at, psr.updated_at, psr.created_at)) AS latest_collection_time
        FROM sources s
        LEFT JOIN place_source_records psr ON psr.source_id = s.source_id
        LEFT JOIN places p ON p.place_id = psr.place_id
        LEFT JOIN place_types pt ON pt.place_type_id = p.place_type_id
        LEFT JOIN reviews r ON r.place_source_id = psr.place_source_id
        GROUP BY s.source_id, s.source_code, s.source_name
        ORDER BY s.source_code
        """
    )


def latest_run() -> dict:
    return query_one(
        """
        SELECT
            sr.scraping_run_id,
            s.source_code,
            s.source_name,
            sr.entity_type,
            sr.run_type,
            sr.status,
            sr.started_at,
            sr.completed_at,
            sr.records_found,
            sr.records_new,
            sr.records_updated,
            sr.pages_total,
            COALESCE(sr.pages_successful, sr.pages_success) AS pages_successful,
            sr.pages_failed,
            sr.stop_reason
        FROM scraping_runs sr
        JOIN sources s ON s.source_id = sr.source_id
        ORDER BY
            CASE WHEN LOWER(sr.status) = ANY(%s) AND sr.completed_at IS NULL THEN 0 ELSE 1 END,
            sr.started_at DESC
        LIMIT 1
        """,
        (list(RUNNING_STATUSES),),
    )


def reviews_over_time(days: int | None) -> pd.DataFrame:
    where = ""
    params: tuple = ()
    if days is not None:
        where = "WHERE created_at >= NOW() - (%s || ' days')::interval"
        params = (days,)
    return query_dataframe(
        f"""
        SELECT
            DATE_TRUNC('day', created_at)::date AS collection_day,
            COUNT(*)::bigint AS reviews_collected
        FROM reviews
        {where}
        GROUP BY collection_day
        ORDER BY collection_day
        """,
        params,
    )


def reviews_by_source() -> pd.DataFrame:
    return query_dataframe(
        """
        SELECT
            s.source_code,
            COUNT(r.review_id)::bigint AS reviews
        FROM sources s
        LEFT JOIN place_source_records psr ON psr.source_id = s.source_id
        LEFT JOIN reviews r ON r.place_source_id = psr.place_source_id
        GROUP BY s.source_code
        ORDER BY reviews DESC, s.source_code
        """
    )


def places_by_category(filters: Filters) -> pd.DataFrame:
    source_sql, source_params = _source_filter(filters.source)
    return query_dataframe(
        f"""
        SELECT
            pt.type_group AS category,
            COUNT(DISTINCT p.place_id)::bigint AS canonical_places
        FROM places p
        JOIN place_types pt ON pt.place_type_id = p.place_type_id
        LEFT JOIN place_source_records psr ON psr.place_id = p.place_id
        LEFT JOIN sources s ON s.source_id = psr.source_id
        WHERE 1 = 1
          {source_sql}
        GROUP BY pt.type_group
        ORDER BY canonical_places DESC, category
        """,
        tuple(source_params),
    )


def top_reviewed_places(filters: Filters, limit: int = 10) -> pd.DataFrame:
    source_sql, source_params = _source_filter(filters.source)
    category_sql, category_params = _category_filter(filters.category)
    params = tuple(source_params + category_params + [limit])
    return query_dataframe(
        f"""
        SELECT
            COALESCE(psr.source_name, p.canonical_name) AS place,
            pt.type_group AS category,
            s.source_code AS source,
            CASE
                WHEN psr.review_count BETWEEN 0 AND 1000000 THEN psr.review_count
                ELSE NULL
            END AS review_count,
            psr.review_score AS rating
        FROM place_source_records psr
        JOIN sources s ON s.source_id = psr.source_id
        JOIN places p ON p.place_id = psr.place_id
        JOIN place_types pt ON pt.place_type_id = p.place_type_id
        WHERE 1 = 1
          {source_sql}
          {category_sql}
        ORDER BY
            CASE
                WHEN psr.review_count BETWEEN 0 AND 1000000 THEN psr.review_count
                ELSE 0
            END DESC,
            psr.review_score DESC NULLS LAST
        LIMIT %s
        """,
        params,
    )


def rating_distribution_by_source() -> pd.DataFrame:
    return query_dataframe(
        """
        SELECT
            s.source_code,
            CASE
                WHEN r.rating_scale IS NOT NULL AND r.rating_scale > 0
                    THEN ROUND((r.review_score / r.rating_scale * 5)::numeric, 1)
                WHEN s.source_code = 'BOOKING' AND r.review_score IS NOT NULL
                    THEN ROUND((r.review_score / 10 * 5)::numeric, 1)
                ELSE ROUND(r.review_score::numeric, 1)
            END AS normalized_rating_5,
            COUNT(*)::bigint AS reviews
        FROM reviews r
        JOIN place_source_records psr ON psr.place_source_id = r.place_source_id
        JOIN sources s ON s.source_id = psr.source_id
        WHERE r.review_score IS NOT NULL
        GROUP BY s.source_code, normalized_rating_5
        ORDER BY s.source_code, normalized_rating_5
        """
    )


def review_languages(limit: int = 8) -> pd.DataFrame:
    return query_dataframe(
        """
        WITH ranked AS (
            SELECT
                COALESCE(NULLIF(language_code, ''), 'Unknown') AS language,
                COUNT(*)::bigint AS reviews,
                ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC) AS rank
            FROM reviews
            GROUP BY COALESCE(NULLIF(language_code, ''), 'Unknown')
        ),
        bucketed AS (
            SELECT
                CASE WHEN rank <= %s THEN language ELSE 'Other' END AS language,
                reviews
            FROM ranked
        )
        SELECT
            language,
            SUM(reviews)::bigint AS reviews
        FROM bucketed
        GROUP BY language
        ORDER BY reviews DESC, language
        """,
        (limit,),
    )


def latest_runs(filters: Filters, limit: int = 30) -> pd.DataFrame:
    clauses = []
    params: list = []
    if filters.source != "All":
        clauses.append("s.source_code = %s")
        params.append(filters.source)
    if filters.run_status != "All":
        clauses.append("UPPER(sr.status) = %s")
        params.append(filters.run_status.upper())
    if filters.category != "All":
        clauses.append("sr.entity_type = %s")
        params.append(filters.category)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(limit)
    return query_dataframe(
        f"""
        SELECT
            sr.started_at,
            s.source_code AS source,
            sr.entity_type,
            sr.run_type,
            sr.status,
            sr.completed_at,
            sr.records_found,
            sr.records_new,
            sr.records_updated,
            COALESCE(sr.pages_successful, sr.pages_success) AS pages_successful,
            sr.pages_failed,
            sr.stop_reason,
            CASE
                WHEN sr.completed_at IS NULL THEN NULL
                ELSE EXTRACT(EPOCH FROM (sr.completed_at - sr.started_at))::bigint
            END AS duration_seconds
        FROM scraping_runs sr
        JOIN sources s ON s.source_id = sr.source_id
        {where}
        ORDER BY sr.started_at DESC
        LIMIT %s
        """,
        tuple(params),
    )


def data_quality() -> pd.DataFrame:
    return query_dataframe(
        """
        WITH metrics AS (
            SELECT
                'Places without coordinates' AS metric,
                COUNT(*) FILTER (
                    WHERE COALESCE(p.latitude, psr.latitude) IS NULL
                       OR COALESCE(p.longitude, psr.longitude) IS NULL
                )::bigint AS issue_count,
                COUNT(*)::bigint AS total_count
            FROM places p
            LEFT JOIN place_source_records psr ON psr.place_id = p.place_id

            UNION ALL

            SELECT
                'Source listings without reviews' AS metric,
                COUNT(*) FILTER (WHERE review_totals.review_count = 0)::bigint AS issue_count,
                COUNT(*)::bigint AS total_count
            FROM place_source_records psr
            LEFT JOIN (
                SELECT place_source_id, COUNT(*) AS review_count
                FROM reviews
                GROUP BY place_source_id
            ) review_totals ON review_totals.place_source_id = psr.place_source_id

            UNION ALL

            SELECT
                'Reviews without source_review_id' AS metric,
                COUNT(*) FILTER (WHERE source_review_id IS NULL OR source_review_id = '')::bigint AS issue_count,
                COUNT(*)::bigint AS total_count
            FROM reviews

            UNION ALL

            SELECT
                'Reviews without language' AS metric,
                COUNT(*) FILTER (WHERE language_code IS NULL OR language_code = '')::bigint AS issue_count,
                COUNT(*)::bigint AS total_count
            FROM reviews

            UNION ALL

            SELECT
                'Reviews without reviewer' AS metric,
                COUNT(*) FILTER (WHERE reviewer_id IS NULL)::bigint AS issue_count,
                COUNT(*)::bigint AS total_count
            FROM reviews

            UNION ALL

            SELECT
                'Duplicate source place IDs' AS metric,
                COALESCE(SUM(duplicate_count - 1), 0)::bigint AS issue_count,
                COUNT(*)::bigint AS total_count
            FROM (
                SELECT source_id, source_place_id, COUNT(*) AS duplicate_count
                FROM place_source_records
                GROUP BY source_id, source_place_id
                HAVING COUNT(*) > 1
            ) duplicates

            UNION ALL

            SELECT
                'Duplicate source review IDs' AS metric,
                COALESCE(SUM(duplicate_count - 1), 0)::bigint AS issue_count,
                COUNT(*)::bigint AS total_count
            FROM (
                SELECT place_source_id, source_review_id, COUNT(*) AS duplicate_count
                FROM reviews
                WHERE source_review_id IS NOT NULL
                GROUP BY place_source_id, source_review_id
                HAVING COUNT(*) > 1
            ) duplicates

            UNION ALL

            SELECT
                'Failed or partial runs' AS metric,
                COUNT(*) FILTER (WHERE LOWER(status) IN ('failed', 'partial'))::bigint AS issue_count,
                COUNT(*)::bigint AS total_count
            FROM scraping_runs
        )
        SELECT
            metric,
            issue_count,
            total_count,
            CASE
                WHEN total_count = 0 THEN 0
                ELSE ROUND((issue_count::numeric / total_count) * 100, 2)
            END AS issue_percent
        FROM metrics
        ORDER BY issue_count DESC, metric
        """
    )


def database_growth() -> pd.DataFrame:
    return query_dataframe(
        """
        WITH place_growth AS (
            SELECT DATE_TRUNC('day', created_at)::date AS day, COUNT(*)::bigint AS places_added
            FROM places
            GROUP BY day
        ),
        review_growth AS (
            SELECT DATE_TRUNC('day', created_at)::date AS day, COUNT(*)::bigint AS reviews_added
            FROM reviews
            GROUP BY day
        )
        SELECT
            COALESCE(place_growth.day, review_growth.day) AS day,
            COALESCE(place_growth.places_added, 0)::bigint AS places_added,
            COALESCE(review_growth.reviews_added, 0)::bigint AS reviews_added
        FROM place_growth
        FULL OUTER JOIN review_growth ON review_growth.day = place_growth.day
        ORDER BY day
        """
    )


def database_size() -> dict:
    return query_one(
        """
        SELECT
            pg_size_pretty(pg_database_size(current_database())) AS database_size,
            pg_size_pretty(pg_total_relation_size('reviews')) AS reviews_table_size,
            pg_size_pretty(pg_total_relation_size('places')) AS places_table_size,
            pg_size_pretty(pg_total_relation_size('place_source_records')) AS source_records_table_size
        """
    )


def filter_options() -> dict[str, list[str]]:
    sources = query_dataframe(
        "SELECT source_code FROM sources ORDER BY source_code"
    )
    categories = query_dataframe(
        "SELECT DISTINCT type_group FROM place_types ORDER BY type_group"
    )
    statuses = query_dataframe(
        "SELECT DISTINCT UPPER(status) AS status FROM scraping_runs WHERE status IS NOT NULL ORDER BY status"
    )
    return {
        "sources": ["All"] + sources.get("source_code", pd.Series(dtype=str)).dropna().tolist(),
        "categories": ["All"] + categories.get("type_group", pd.Series(dtype=str)).dropna().tolist(),
        "statuses": ["All"] + statuses.get("status", pd.Series(dtype=str)).dropna().tolist(),
    }
