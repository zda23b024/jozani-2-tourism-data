from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from db import query_dataframe, query_one


RUNNING_STATUSES = ("running", "started", "collecting", "in_progress")
SUCCESS_STATUSES = ("success", "completed", "complete")
FAILED_STATUSES = ("failed", "error")
WARNING_STATUSES = ("partial", "warning", "warn")


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


def _search_filter(search: str, columns: list[str]) -> tuple[str, list]:
    clean = search.strip()
    if not clean:
        return "", []
    clause = " OR ".join(f"{column} ILIKE %s" for column in columns)
    return f" AND ({clause})", [f"%{clean}%"] * len(columns)


def connection_status() -> dict:
    return query_one(
        """
        SELECT
            current_database() AS database_name,
            current_user AS database_user,
            NOW() AS checked_at,
            split_part(version(), ' on ', 1) AS server_version
        """
    )


def overview_kpis(filters: Filters) -> dict:
    source_sql, source_params = _source_filter(filters.source)
    category_sql, category_params = _category_filter(filters.category)
    params = tuple(source_params + category_params)
    values = query_one(
        f"""
        WITH filtered_records AS (
            SELECT
                p.place_id,
                psr.place_source_id,
                s.source_id,
                GREATEST(
                    COALESCE(psr.last_scraped_at, '-infinity'::timestamptz),
                    COALESCE(psr.updated_at, '-infinity'::timestamptz),
                    COALESCE(p.updated_at, '-infinity'::timestamptz)
                ) AS updated_at
            FROM places p
            JOIN place_types pt ON pt.place_type_id = p.place_type_id
            LEFT JOIN place_source_records psr ON psr.place_id = p.place_id
            LEFT JOIN sources s ON s.source_id = psr.source_id
            WHERE 1 = 1
              {source_sql}
              {category_sql}
        ),
        filtered_reviews AS (
            SELECT
                r.review_id,
                r.created_at,
                r.review_text,
                r.positive_text,
                r.negative_text
            FROM reviews r
            JOIN filtered_records fr ON fr.place_source_id = r.place_source_id
        )
        SELECT
            (SELECT COUNT(DISTINCT place_id)::bigint FROM filtered_records) AS canonical_places,
            (SELECT COUNT(DISTINCT place_source_id)::bigint FROM filtered_records) AS source_records,
            (SELECT COUNT(*)::bigint FROM filtered_reviews) AS total_reviews,
            (SELECT COUNT(*)::bigint FROM filtered_reviews
             WHERE COALESCE(NULLIF(TRIM(review_text), ''), NULLIF(TRIM(positive_text), ''), NULLIF(TRIM(negative_text), '')) IS NOT NULL
            ) AS reviews_with_text,
            (SELECT COUNT(DISTINCT source_id)::bigint FROM filtered_records WHERE place_source_id IS NOT NULL) AS active_sources,
            GREATEST(
                COALESCE((SELECT MAX(updated_at) FROM filtered_records), '-infinity'::timestamptz),
                COALESCE((SELECT MAX(created_at) FROM filtered_reviews), '-infinity'::timestamptz)
            ) AS latest_database_update
        """,
        params,
    )
    if str(values.get("latest_database_update")) == "-infinity":
        values["latest_database_update"] = None
    run = query_one(
        """
        SELECT MAX(completed_at) AS last_successful_collection
        FROM scraping_runs
        WHERE LOWER(status) = ANY(%s)
          AND completed_at IS NOT NULL
        """,
        (list(SUCCESS_STATUSES),),
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
    return {**values, **run, **running}


def source_coverage() -> pd.DataFrame:
    return query_dataframe(
        """
        WITH review_counts AS (
            SELECT
                place_source_id,
                COUNT(*)::bigint AS reviews,
                MAX(created_at) AS last_review_at
            FROM reviews
            GROUP BY place_source_id
        )
        SELECT
            s.source_code AS source,
            COUNT(DISTINCT psr.place_source_id) FILTER (WHERE pt.type_group = 'Accommodation')::bigint AS accommodations_hotels,
            COUNT(DISTINCT psr.place_source_id) FILTER (WHERE pt.type_group IN ('Attraction', 'Activity'))::bigint AS attractions,
            COUNT(DISTINCT psr.place_source_id) FILTER (WHERE pt.type_group = 'Restaurant')::bigint AS restaurants,
            COALESCE(SUM(rc.reviews), 0)::bigint AS reviews,
            MAX(GREATEST(
                COALESCE(psr.last_scraped_at, '-infinity'::timestamptz),
                COALESCE(psr.updated_at, '-infinity'::timestamptz),
                COALESCE(rc.last_review_at, '-infinity'::timestamptz)
            )) AS last_update
        FROM sources s
        LEFT JOIN place_source_records psr ON psr.source_id = s.source_id
        LEFT JOIN places p ON p.place_id = psr.place_id
        LEFT JOIN place_types pt ON pt.place_type_id = p.place_type_id
        LEFT JOIN review_counts rc ON rc.place_source_id = psr.place_source_id
        GROUP BY s.source_code
        ORDER BY s.source_code
        """
    )


def places_by_source_category(filters: Filters) -> pd.DataFrame:
    source_sql, source_params = _source_filter(filters.source)
    category_sql, category_params = _category_filter(filters.category)
    return query_dataframe(
        f"""
        SELECT
            s.source_code AS source,
            CASE
                WHEN pt.type_group = 'Accommodation' THEN 'Accommodations / Hotels'
                WHEN pt.type_group IN ('Attraction', 'Activity') THEN 'Attractions'
                WHEN pt.type_group = 'Restaurant' THEN 'Restaurants'
                ELSE pt.type_group
            END AS category,
            COUNT(DISTINCT psr.place_source_id)::bigint AS source_records,
            COUNT(DISTINCT p.place_id)::bigint AS canonical_places
        FROM place_source_records psr
        JOIN sources s ON s.source_id = psr.source_id
        JOIN places p ON p.place_id = psr.place_id
        JOIN place_types pt ON pt.place_type_id = p.place_type_id
        WHERE 1 = 1
          {source_sql}
          {category_sql}
        GROUP BY
            s.source_code,
            CASE
                WHEN pt.type_group = 'Accommodation' THEN 'Accommodations / Hotels'
                WHEN pt.type_group IN ('Attraction', 'Activity') THEN 'Attractions'
                WHEN pt.type_group = 'Restaurant' THEN 'Restaurants'
                ELSE pt.type_group
            END
        ORDER BY source_records DESC, source, category
        """,
        tuple(source_params + category_params),
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


def top_reviewed_places(filters: Filters, limit: int = 10) -> pd.DataFrame:
    source_sql, source_params = _source_filter(filters.source)
    category_sql, category_params = _category_filter(filters.category)
    return query_dataframe(
        f"""
        WITH grouped AS (
            SELECT
                COALESCE(psr.source_name, p.canonical_name) AS place,
                pt.type_group AS category,
                s.source_code AS source,
                COUNT(r.review_id)::bigint AS stored_reviews,
                psr.review_score AS source_rating,
                CASE
                    WHEN s.source_code = 'BOOKING' AND psr.review_score IS NOT NULL THEN psr.review_score::text || ' / 10'
                    WHEN s.source_code = 'TRIPADVISOR' AND psr.review_score IS NOT NULL THEN psr.review_score::text || ' / 5'
                    WHEN psr.review_score IS NOT NULL THEN psr.review_score::text
                    ELSE NULL
                END AS rating
            FROM place_source_records psr
            JOIN sources s ON s.source_id = psr.source_id
            JOIN places p ON p.place_id = psr.place_id
            JOIN place_types pt ON pt.place_type_id = p.place_type_id
            LEFT JOIN reviews r ON r.place_source_id = psr.place_source_id
            WHERE 1 = 1
              {source_sql}
              {category_sql}
            GROUP BY psr.place_source_id, p.canonical_name, pt.type_group, s.source_code, psr.source_name, psr.review_score
            HAVING COUNT(r.review_id) > 0
        )
        SELECT
            ROW_NUMBER() OVER (ORDER BY stored_reviews DESC, source_rating DESC NULLS LAST, place) AS "#",
            place AS "Place",
            category AS "Category",
            source AS "Source",
            stored_reviews AS "Stored Reviews",
            rating AS "Rating"
        FROM grouped
        ORDER BY stored_reviews DESC, source_rating DESC NULLS LAST, place
        LIMIT %s
        """,
        tuple(source_params + category_params + [limit]),
    )


def recent_runs(limit: int = 6) -> pd.DataFrame:
    return query_dataframe(
        """
        WITH review_totals AS (
            SELECT
                s.source_id,
                COUNT(r.review_id)::bigint AS reviews
            FROM sources s
            LEFT JOIN place_source_records psr ON psr.source_id = s.source_id
            LEFT JOIN reviews r ON r.place_source_id = psr.place_source_id
            GROUP BY s.source_id
        ),
        log_errors AS (
            SELECT
                scraping_run_id,
                MAX(NULLIF(error_message, '')) AS last_error
            FROM scraping_logs
            GROUP BY scraping_run_id
        )
        SELECT
            s.source_code AS source,
            sr.entity_type AS category,
            sr.started_at AS started,
            sr.status,
            COALESCE(sr.records_found, sr.records_new, sr.records_updated, 0) AS records,
            COALESCE(rt.reviews, 0) AS reviews,
            COALESCE(sr.stop_reason, le.last_error, 'Recorded run') AS message
        FROM scraping_runs sr
        JOIN sources s ON s.source_id = sr.source_id
        LEFT JOIN review_totals rt ON rt.source_id = s.source_id
        LEFT JOIN log_errors le ON le.scraping_run_id = sr.scraping_run_id
        ORDER BY sr.started_at DESC
        LIMIT %s
        """,
        (limit,),
    )


def explorer_places(
    source: str = "All",
    category: str = "All",
    search: str = "",
    limit: int = 100,
    offset: int = 0,
) -> pd.DataFrame:
    source_sql, source_params = _source_filter(source)
    category_sql, category_params = _category_filter(category)
    search_sql, search_params = _search_filter(
        search,
        ["COALESCE(psr.source_name, p.canonical_name)", "COALESCE(l.location_name, '')"],
    )
    return query_dataframe(
        f"""
        SELECT
            COALESCE(psr.source_name, p.canonical_name) AS place_name,
            pt.type_group AS category,
            s.source_code AS source,
            COALESCE(l.location_name, l.region_name, l.district_name, '') AS location,
            psr.review_score AS rating,
            psr.review_count,
            COALESCE(psr.last_scraped_at, psr.updated_at, psr.created_at) AS last_updated
        FROM place_source_records psr
        JOIN sources s ON s.source_id = psr.source_id
        JOIN places p ON p.place_id = psr.place_id
        JOIN place_types pt ON pt.place_type_id = p.place_type_id
        LEFT JOIN locations l ON l.location_id = p.location_id
        WHERE 1 = 1
          {source_sql}
          {category_sql}
          {search_sql}
        ORDER BY last_updated DESC NULLS LAST, place_name
        LIMIT %s OFFSET %s
        """,
        tuple(source_params + category_params + search_params + [limit, offset]),
    )


def explorer_count(source: str = "All", category: str = "All", search: str = "") -> dict:
    source_sql, source_params = _source_filter(source)
    category_sql, category_params = _category_filter(category)
    search_sql, search_params = _search_filter(
        search,
        ["COALESCE(psr.source_name, p.canonical_name)", "COALESCE(l.location_name, '')"],
    )
    return query_one(
        f"""
        SELECT COUNT(*)::bigint AS records
        FROM place_source_records psr
        JOIN sources s ON s.source_id = psr.source_id
        JOIN places p ON p.place_id = psr.place_id
        JOIN place_types pt ON pt.place_type_id = p.place_type_id
        LEFT JOIN locations l ON l.location_id = p.location_id
        WHERE 1 = 1
          {source_sql}
          {category_sql}
          {search_sql}
        """,
        tuple(source_params + category_params + search_params),
    )


def review_metrics() -> dict:
    return query_one(
        """
        SELECT
            COUNT(*)::bigint AS total_reviews,
            COUNT(*) FILTER (
                WHERE COALESCE(NULLIF(TRIM(review_text), ''), NULLIF(TRIM(positive_text), ''), NULLIF(TRIM(negative_text), '')) IS NOT NULL
            )::bigint AS reviews_with_text,
            COUNT(DISTINCT NULLIF(language_code, ''))::bigint AS languages,
            COUNT(DISTINCT reviewer_id) FILTER (WHERE reviewer_id IS NOT NULL)::bigint AS reviewers,
            COUNT(*) FILTER (WHERE review_score IS NOT NULL)::bigint AS reviews_with_rating
        FROM reviews
        """
    )


def review_language_options() -> list[str]:
    frame = query_dataframe(
        """
        SELECT DISTINCT COALESCE(NULLIF(language_code, ''), 'Unknown') AS language
        FROM reviews
        ORDER BY language
        """
    )
    return ["All"] + frame.get("language", pd.Series(dtype=str)).dropna().tolist()


def sample_reviews(
    source: str = "All",
    category: str = "All",
    place_search: str = "",
    language: str = "All",
    rating_min: float | None = None,
    rating_max: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> pd.DataFrame:
    clauses: list[str] = []
    params: list = []
    if source != "All":
        clauses.append("s.source_code = %s")
        params.append(source)
    if category != "All":
        clauses.append("pt.type_group = %s")
        params.append(category)
    if place_search.strip():
        clauses.append("COALESCE(psr.source_name, p.canonical_name) ILIKE %s")
        params.append(f"%{place_search.strip()}%")
    if language != "All":
        if language == "Unknown":
            clauses.append("(r.language_code IS NULL OR r.language_code = '')")
        else:
            clauses.append("r.language_code = %s")
            params.append(language)
    if rating_min is not None:
        clauses.append("r.review_score >= %s")
        params.append(rating_min)
    if rating_max is not None:
        clauses.append("r.review_score <= %s")
        params.append(rating_max)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend([limit, offset])
    return query_dataframe(
        f"""
        SELECT
            COALESCE(psr.source_name, p.canonical_name) AS place,
            s.source_code AS source,
            pt.type_group AS category,
            r.review_score AS rating,
            r.rating_scale,
            r.review_date,
            COALESCE(NULLIF(r.language_code, ''), 'Unknown') AS language,
            COALESCE(NULLIF(rv.reviewer_name, ''), NULLIF(rv.username, ''), 'Unknown') AS reviewer,
            rv.country_name AS reviewer_country,
            r.review_title,
            COALESCE(NULLIF(r.review_text, ''), NULLIF(r.positive_text, ''), NULLIF(r.negative_text, '')) AS review_text
        FROM reviews r
        JOIN place_source_records psr ON psr.place_source_id = r.place_source_id
        JOIN sources s ON s.source_id = psr.source_id
        JOIN places p ON p.place_id = psr.place_id
        JOIN place_types pt ON pt.place_type_id = p.place_type_id
        LEFT JOIN reviewers rv ON rv.reviewer_id = r.reviewer_id
        {where}
        ORDER BY r.review_date DESC NULLS LAST, r.created_at DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )


def sample_reviews_count(
    source: str = "All",
    category: str = "All",
    place_search: str = "",
    language: str = "All",
    rating_min: float | None = None,
    rating_max: float | None = None,
) -> dict:
    clauses: list[str] = []
    params: list = []
    if source != "All":
        clauses.append("s.source_code = %s")
        params.append(source)
    if category != "All":
        clauses.append("pt.type_group = %s")
        params.append(category)
    if place_search.strip():
        clauses.append("COALESCE(psr.source_name, p.canonical_name) ILIKE %s")
        params.append(f"%{place_search.strip()}%")
    if language != "All":
        if language == "Unknown":
            clauses.append("(r.language_code IS NULL OR r.language_code = '')")
        else:
            clauses.append("r.language_code = %s")
            params.append(language)
    if rating_min is not None:
        clauses.append("r.review_score >= %s")
        params.append(rating_min)
    if rating_max is not None:
        clauses.append("r.review_score <= %s")
        params.append(rating_max)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return query_one(
        f"""
        SELECT COUNT(*)::bigint AS records
        FROM reviews r
        JOIN place_source_records psr ON psr.place_source_id = r.place_source_id
        JOIN sources s ON s.source_id = psr.source_id
        JOIN places p ON p.place_id = psr.place_id
        JOIN place_types pt ON pt.place_type_id = p.place_type_id
        {where}
        """,
        tuple(params),
    )


def health_summary() -> dict:
    return query_one(
        """
        SELECT
            MAX(completed_at) FILTER (WHERE LOWER(status) = ANY(%s)) AS last_successful_run,
            MAX(started_at) FILTER (WHERE LOWER(status) = ANY(%s)) AS last_failed_run,
            COUNT(*) FILTER (WHERE LOWER(status) = ANY(%s))::bigint AS successful_runs,
            COUNT(*) FILTER (WHERE LOWER(status) = ANY(%s))::bigint AS failed_runs,
            COUNT(*) FILTER (WHERE LOWER(status) = ANY(%s) AND completed_at IS NULL)::bigint AS running_jobs
        FROM scraping_runs
        """,
        (
            list(SUCCESS_STATUSES),
            list(FAILED_STATUSES),
            list(SUCCESS_STATUSES),
            list(FAILED_STATUSES),
            list(RUNNING_STATUSES),
        ),
    )


def collection_status_by_source() -> pd.DataFrame:
    return query_dataframe(
        """
        WITH latest AS (
            SELECT
                s.source_code AS source,
                COALESCE(sr.entity_type, sr.run_type) AS category,
                sr.status,
                sr.started_at,
                sr.completed_at,
                sr.stop_reason,
                ROW_NUMBER() OVER (
                    PARTITION BY s.source_code, COALESCE(sr.entity_type, sr.run_type)
                    ORDER BY sr.started_at DESC
                ) AS rn
            FROM scraping_runs sr
            JOIN sources s ON s.source_id = sr.source_id
        )
        SELECT
            source,
            category,
            status,
            started_at AS last_run,
            completed_at,
            stop_reason
        FROM latest
        WHERE rn = 1
        ORDER BY source, category
        """
    )


def collection_health(filters: Filters, limit: int = 80) -> pd.DataFrame:
    clauses: list[str] = []
    params: list = []
    if filters.source != "All":
        clauses.append("s.source_code = %s")
        params.append(filters.source)
    if filters.category != "All":
        clauses.append("sr.entity_type = %s")
        params.append(filters.category)
    if filters.run_status != "All":
        clauses.append("UPPER(sr.status) = %s")
        params.append(filters.run_status.upper())
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(limit)
    return query_dataframe(
        f"""
        WITH log_errors AS (
            SELECT
                scraping_run_id,
                COUNT(*) FILTER (WHERE COALESCE(error_message, '') <> '' OR UPPER(log_level) IN ('ERROR', 'FAILED')) AS error_logs,
                MAX(NULLIF(error_message, '')) AS last_error
            FROM scraping_logs
            GROUP BY scraping_run_id
        )
        SELECT
            s.source_code AS source,
            sr.entity_type AS category,
            sr.run_type,
            sr.status,
            sr.started_at AS last_run,
            sr.completed_at,
            sr.records_found,
            sr.records_new,
            sr.records_updated,
            COALESCE(sr.pages_successful, sr.pages_success) AS pages_successful,
            sr.pages_failed,
            sr.errors_count,
            CASE
                WHEN sr.completed_at IS NULL THEN NULL
                ELSE EXTRACT(EPOCH FROM (sr.completed_at - sr.started_at))::bigint
            END AS duration_seconds,
            COALESCE(sr.stop_reason, le.last_error) AS error_summary
        FROM scraping_runs sr
        JOIN sources s ON s.source_id = sr.source_id
        LEFT JOIN log_errors le ON le.scraping_run_id = sr.scraping_run_id
        {where}
        ORDER BY sr.started_at DESC
        LIMIT %s
        """,
        tuple(params),
    )


def database_summary() -> dict:
    return query_one(
        """
        SELECT
            (SELECT COUNT(*)::bigint FROM sources) AS sources,
            (SELECT COUNT(*)::bigint FROM places) AS canonical_places,
            (SELECT COUNT(*)::bigint FROM place_source_records) AS source_records,
            (SELECT COUNT(*)::bigint FROM reviews) AS reviews,
            (SELECT COUNT(*)::bigint FROM reviewers) AS reviewers,
            (SELECT COUNT(*)::bigint FROM places p JOIN place_types pt ON pt.place_type_id = p.place_type_id WHERE pt.type_group = 'Accommodation') AS accommodations,
            (SELECT COUNT(*)::bigint FROM places p JOIN place_types pt ON pt.place_type_id = p.place_type_id WHERE pt.type_group IN ('Attraction', 'Activity')) AS attractions,
            (SELECT COUNT(*)::bigint FROM places p JOIN place_types pt ON pt.place_type_id = p.place_type_id WHERE pt.type_group = 'Restaurant') AS restaurants,
            GREATEST(
                COALESCE((SELECT MAX(updated_at) FROM places), 'epoch'::timestamptz),
                COALESCE((SELECT MAX(updated_at) FROM place_source_records), 'epoch'::timestamptz),
                COALESCE((SELECT MAX(updated_at) FROM reviews), 'epoch'::timestamptz)
            ) AS latest_database_update
        """
    )


def entity_counts() -> pd.DataFrame:
    return query_dataframe(
        """
        SELECT 'sources' AS entity, COUNT(*)::bigint AS records FROM sources
        UNION ALL SELECT 'places', COUNT(*)::bigint FROM places
        UNION ALL SELECT 'place_source_records', COUNT(*)::bigint FROM place_source_records
        UNION ALL SELECT 'accommodation_source_details', COUNT(*)::bigint FROM accommodation_source_details
        UNION ALL SELECT 'attraction_source_details', COUNT(*)::bigint FROM attraction_source_details
        UNION ALL SELECT 'restaurant_source_details', COUNT(*)::bigint FROM restaurant_source_details
        UNION ALL SELECT 'reviewers', COUNT(*)::bigint FROM reviewers
        UNION ALL SELECT 'reviews', COUNT(*)::bigint FROM reviews
        UNION ALL SELECT 'review_category_scores', COUNT(*)::bigint FROM review_category_scores
        UNION ALL SELECT 'amenities', COUNT(*)::bigint FROM amenities
        UNION ALL SELECT 'place_source_amenities', COUNT(*)::bigint FROM place_source_amenities
        UNION ALL SELECT 'locations', COUNT(*)::bigint FROM locations
        UNION ALL SELECT 'scraping_runs', COUNT(*)::bigint FROM scraping_runs
        UNION ALL SELECT 'scraping_logs', COUNT(*)::bigint FROM scraping_logs
        ORDER BY entity
        """
    )


def data_quality() -> pd.DataFrame:
    return query_dataframe(
        """
        WITH metrics AS (
            SELECT
                'Reviews with non-empty text' AS metric,
                COUNT(*) FILTER (
                    WHERE COALESCE(NULLIF(TRIM(review_text), ''), NULLIF(TRIM(positive_text), ''), NULLIF(TRIM(negative_text), '')) IS NOT NULL
                )::bigint AS numerator,
                COUNT(*)::bigint AS denominator
            FROM reviews

            UNION ALL

            SELECT
                'Reviews with rating',
                COUNT(*) FILTER (WHERE review_score IS NOT NULL)::bigint,
                COUNT(*)::bigint
            FROM reviews

            UNION ALL

            SELECT
                'Places with location information',
                COUNT(DISTINCT p.place_id) FILTER (
                    WHERE p.location_id IS NOT NULL
                       OR COALESCE(p.latitude, psr.latitude) IS NOT NULL
                       OR COALESCE(p.longitude, psr.longitude) IS NOT NULL
                )::bigint,
                COUNT(DISTINCT p.place_id)::bigint
            FROM places p
            LEFT JOIN place_source_records psr ON psr.place_id = p.place_id

            UNION ALL

            SELECT
                'Source records with source IDs',
                COUNT(*) FILTER (WHERE source_place_id IS NOT NULL AND source_place_id <> '')::bigint,
                COUNT(*)::bigint
            FROM place_source_records

            UNION ALL

            SELECT
                'Duplicate source review IDs',
                COALESCE(SUM(duplicate_count - 1), 0)::bigint,
                COUNT(*)::bigint
            FROM (
                SELECT place_source_id, source_review_id, COUNT(*) AS duplicate_count
                FROM reviews
                WHERE source_review_id IS NOT NULL AND source_review_id <> ''
                GROUP BY place_source_id, source_review_id
                HAVING COUNT(*) > 1
            ) duplicates
        )
        SELECT
            metric,
            numerator,
            denominator,
            CASE
                WHEN denominator = 0 THEN 0
                ELSE ROUND((numerator::numeric / denominator) * 100, 2)
            END AS percent
        FROM metrics
        ORDER BY metric
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
    sources = query_dataframe("SELECT source_code FROM sources ORDER BY source_code")
    categories = query_dataframe("SELECT DISTINCT type_group FROM place_types ORDER BY type_group")
    statuses = query_dataframe(
        "SELECT DISTINCT UPPER(status) AS status FROM scraping_runs WHERE status IS NOT NULL ORDER BY status"
    )
    return {
        "sources": ["All"] + sources.get("source_code", pd.Series(dtype=str)).dropna().tolist(),
        "categories": ["All"] + categories.get("type_group", pd.Series(dtype=str)).dropna().tolist(),
        "statuses": ["All"] + statuses.get("status", pd.Series(dtype=str)).dropna().tolist(),
    }
