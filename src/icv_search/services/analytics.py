"""Search analytics service functions."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Avg, Count
from django.utils import timezone

logger = logging.getLogger(__name__)


def _get_log_mode() -> str:
    """Return the current ``ICV_SEARCH_LOG_MODE`` setting (default ``"individual"``)."""
    from django.conf import settings as django_settings

    return getattr(django_settings, "ICV_SEARCH_LOG_MODE", "individual")


def get_popular_queries(
    index_name: str,
    *,
    days: int = 7,
    limit: int = 20,
    tenant_id: str = "",
) -> list[dict]:
    """Return the most frequently used queries for a given index.

    When ``ICV_SEARCH_LOG_MODE`` is ``"aggregate"`` the result is derived from
    :class:`~icv_search.models.aggregates.SearchQueryAggregate` totals.
    Otherwise ``SearchQueryLog`` rows are counted directly.

    Args:
        index_name: Logical name of the search index.
        days: Look-back window in days.
        limit: Maximum number of results to return.
        tenant_id: Restrict results to a specific tenant. Empty string returns
            results across all tenants.

    Returns:
        List of dicts with ``query`` and ``count`` keys, ordered by count
        descending.
    """
    if _get_log_mode() == "aggregate":
        from django.db.models import Sum

        from icv_search.models.aggregates import SearchQueryAggregate

        since = timezone.now().date() - timedelta(days=days)
        qs = SearchQueryAggregate.objects.filter(index_name=index_name, date__gte=since)

        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)

        return list(qs.values("query").annotate(count=Sum("total_count")).order_by("-count")[:limit])

    from icv_search.models.analytics import SearchQueryLog

    since = timezone.now() - timedelta(days=days)
    qs = SearchQueryLog.objects.filter(index_name=index_name, created_at__gte=since)

    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)

    return list(qs.values("query").annotate(count=Count("id")).order_by("-count")[:limit])


def get_zero_result_queries(
    index_name: str,
    *,
    days: int = 7,
    limit: int = 20,
    tenant_id: str = "",
) -> list[dict]:
    """Return queries that returned no results for a given index.

    These are valuable for identifying gaps in the search index content or
    configuration.

    When ``ICV_SEARCH_LOG_MODE`` is ``"aggregate"`` the result is derived from
    :class:`~icv_search.models.aggregates.SearchQueryAggregate` rows where
    ``zero_result_count > 0``.

    Args:
        index_name: Logical name of the search index.
        days: Look-back window in days.
        limit: Maximum number of results to return.
        tenant_id: Restrict results to a specific tenant.

    Returns:
        List of dicts with ``query`` and ``count`` keys, ordered by count
        descending.
    """
    if _get_log_mode() == "aggregate":
        from django.db.models import Sum

        from icv_search.models.aggregates import SearchQueryAggregate

        since = timezone.now().date() - timedelta(days=days)
        qs = SearchQueryAggregate.objects.filter(
            index_name=index_name,
            date__gte=since,
            zero_result_count__gt=0,
        )

        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)

        return list(qs.values("query").annotate(count=Sum("zero_result_count")).order_by("-count")[:limit])

    from icv_search.models.analytics import SearchQueryLog

    since = timezone.now() - timedelta(days=days)
    qs = SearchQueryLog.objects.filter(
        index_name=index_name,
        is_zero_result=True,
        created_at__gte=since,
    )

    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)

    return list(qs.values("query").annotate(count=Count("id")).order_by("-count")[:limit])


def get_search_stats(
    index_name: str,
    *,
    days: int = 7,
    tenant_id: str = "",
) -> dict:
    """Return aggregate search statistics for a given index.

    When ``ICV_SEARCH_LOG_MODE`` is ``"aggregate"`` statistics are computed
    from :class:`~icv_search.models.aggregates.SearchQueryAggregate` sums.
    Otherwise ``SearchQueryLog`` rows are aggregated directly.

    Args:
        index_name: Logical name of the search index.
        days: Look-back window in days.
        tenant_id: Restrict results to a specific tenant.

    Returns:
        Dict with the following keys:

        - ``total_queries`` (int): Total number of logged queries.
        - ``zero_result_count`` (int): Queries that returned no hits.
        - ``zero_result_rate`` (float): Fraction of queries with zero results
          (0.0 – 1.0). ``0.0`` when there are no queries.
        - ``avg_processing_time_ms`` (float | None): Mean engine processing
          time in milliseconds. ``None`` when there are no queries.
    """
    if _get_log_mode() == "aggregate":
        from django.db.models import Sum

        from icv_search.models.aggregates import SearchQueryAggregate

        since = timezone.now().date() - timedelta(days=days)
        qs = SearchQueryAggregate.objects.filter(index_name=index_name, date__gte=since)

        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)

        agg = qs.aggregate(
            total_queries=Sum("total_count"),
            zero_result_count=Sum("zero_result_count"),
            total_processing_time_ms=Sum("total_processing_time_ms"),
        )

        total = agg["total_queries"] or 0
        zero = agg["zero_result_count"] or 0
        total_ms = agg["total_processing_time_ms"]

        return {
            "total_queries": total,
            "zero_result_count": zero,
            "zero_result_rate": (zero / total) if total > 0 else 0.0,
            "avg_processing_time_ms": (total_ms / total) if total > 0 and total_ms is not None else None,
        }

    from icv_search.models.analytics import SearchQueryLog

    since = timezone.now() - timedelta(days=days)
    qs = SearchQueryLog.objects.filter(index_name=index_name, created_at__gte=since)

    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)

    aggregates = qs.aggregate(
        total_queries=Count("id"),
        zero_result_count=Count("id", filter=models_filter(is_zero_result=True)),
        avg_processing_time_ms=Avg("processing_time_ms"),
    )

    total = aggregates["total_queries"] or 0
    zero = aggregates["zero_result_count"] or 0

    return {
        "total_queries": total,
        "zero_result_count": zero,
        "zero_result_rate": (zero / total) if total > 0 else 0.0,
        "avg_processing_time_ms": aggregates["avg_processing_time_ms"],
    }


def get_query_trend(
    query: str,
    index_name: str,
    *,
    days: int = 30,
    tenant_id: str = "",
) -> list[dict]:
    """Return a day-by-day trend for a specific query against an index.

    Always reads from
    :class:`~icv_search.models.aggregates.SearchQueryAggregate` regardless of
    the current ``ICV_SEARCH_LOG_MODE``.

    Args:
        query: The search query string to analyse (matched case-insensitively
            after stripping whitespace).
        index_name: Logical name of the search index.
        days: Number of calendar days to include (default 30).
        tenant_id: Restrict results to a specific tenant.

    Returns:
        List of dicts ordered by ``date`` ascending, each with:

        - ``date`` (datetime.date): Calendar day.
        - ``count`` (int): Total queries on that day.
        - ``zero_result_count`` (int): Zero-result queries on that day.
        - ``avg_processing_time_ms`` (float | None): Average processing time on
          that day, or ``None`` if ``total_count`` is 0.
    """
    from icv_search.models.aggregates import SearchQueryAggregate

    normalised = query.strip().lower()
    since = timezone.now().date() - timedelta(days=days)

    qs = SearchQueryAggregate.objects.filter(
        index_name=index_name,
        query=normalised,
        date__gte=since,
    )

    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)

    rows = qs.order_by("date").values("date", "total_count", "zero_result_count", "total_processing_time_ms")

    result = []
    for row in rows:
        total = row["total_count"] or 0
        total_ms = row["total_processing_time_ms"]
        result.append(
            {
                "date": row["date"],
                "count": total,
                "zero_result_count": row["zero_result_count"] or 0,
                "avg_processing_time_ms": (total_ms / total) if total > 0 and total_ms is not None else None,
            }
        )

    return result


def clear_query_aggregates(*, days_older_than: int = 90) -> int:
    """Delete search query aggregate rows older than the given number of days.

    Args:
        days_older_than: Aggregate rows with a ``date`` more than this many
            days in the past are deleted.

    Returns:
        Number of rows deleted.
    """
    from icv_search.models.aggregates import SearchQueryAggregate

    cutoff = timezone.now().date() - timedelta(days=days_older_than)
    deleted_count, _ = SearchQueryAggregate.objects.filter(date__lt=cutoff).delete()
    logger.info(
        "Deleted %d old search query aggregates (older than %d days).",
        deleted_count,
        days_older_than,
    )
    return deleted_count


def models_filter(**kwargs):  # type: ignore[return]
    """Thin wrapper around ``django.db.models.Q`` for use in aggregations.

    Exists solely so that the import of ``django.db.models.Q`` is kept local
    to the services module and does not pollute the module namespace.
    """
    from django.db.models import Q

    return Q(**kwargs)


def clear_query_logs(*, days_older_than: int = 30) -> int:
    """Delete search query logs older than the given number of days.

    Args:
        days_older_than: Records created more than this many days ago are
            deleted.

    Returns:
        Number of records deleted.
    """
    from icv_search.models.analytics import SearchQueryLog

    cutoff = timezone.now() - timedelta(days=days_older_than)
    deleted_count, _ = SearchQueryLog.objects.filter(created_at__lt=cutoff).delete()
    logger.info("Deleted %d old search query logs (older than %d days).", deleted_count, days_older_than)
    return deleted_count
