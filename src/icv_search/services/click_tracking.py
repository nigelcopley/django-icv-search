"""Click tracking service functions."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.db.models import Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


def log_click(
    index_name: str,
    query: str,
    document_id: str,
    position: int,
    tenant_id: str = "",
    metadata: dict | None = None,
) -> None:
    """Record a click event from a search results page.

    When ``ICV_SEARCH_CLICK_TRACKING`` is ``False`` this function is a no-op.
    Failures are caught and logged at WARNING level — a failing click log
    must never break the user experience (BR-020).

    Args:
        index_name: Which search index the click occurred on.
        query: The query that produced the clicked result.
        document_id: The primary key of the clicked document.
        position: Zero-based position of the document in the result set.
        tenant_id: Multi-tenant scoping.
        metadata: Arbitrary extra data (user_id, session_id, etc.).
    """
    from django.conf import settings as django_settings

    if not getattr(django_settings, "ICV_SEARCH_CLICK_TRACKING", False):
        return

    try:
        from icv_search.models.click_tracking import SearchClick

        SearchClick.objects.create(
            index_name=index_name,
            query=query,
            document_id=str(document_id),
            position=position,
            tenant_id=tenant_id,
            metadata=metadata or {},
        )
    except Exception:
        logger.warning(
            "Failed to log click for document '%s' in index '%s'.",
            document_id,
            index_name,
            exc_info=True,
        )


def get_click_through_rate(
    index_name: str,
    query: str,
    days: int = 7,
    tenant_id: str = "",
) -> float:
    """Return the click-through rate for a query over a look-back window.

    CTR is calculated as ``total_clicks / total_searches``.  Data is read from
    :class:`~icv_search.models.click_tracking.SearchClickAggregate` (clicks)
    and :class:`~icv_search.models.aggregates.SearchQueryAggregate` (searches).
    The query string is normalised (stripped and lowercased) before matching.

    Args:
        index_name: Logical name of the search index.
        query: The search query string to calculate CTR for.
        days: Look-back window in days.
        tenant_id: Restrict results to a specific tenant.

    Returns:
        CTR as a float between 0.0 and 1.0.  Returns 0.0 when no search data
        exists for the query.
    """
    from icv_search.models.aggregates import SearchQueryAggregate
    from icv_search.models.click_tracking import SearchClickAggregate

    normalised = query.strip().lower()
    since = timezone.now().date() - timedelta(days=days)

    search_qs = SearchQueryAggregate.objects.filter(
        index_name=index_name,
        query=normalised,
        date__gte=since,
    )
    if tenant_id:
        search_qs = search_qs.filter(tenant_id=tenant_id)

    total_searches = search_qs.aggregate(total=Sum("total_count"))["total"] or 0
    if total_searches == 0:
        return 0.0

    click_qs = SearchClickAggregate.objects.filter(
        index_name=index_name,
        query=normalised,
        date__gte=since,
    )
    if tenant_id:
        click_qs = click_qs.filter(tenant_id=tenant_id)

    total_clicks = click_qs.aggregate(total=Sum("click_count"))["total"] or 0
    return total_clicks / total_searches


def get_top_clicked_documents(
    index_name: str,
    query: str,
    days: int = 7,
    limit: int = 10,
    tenant_id: str = "",
) -> list[dict[str, Any]]:
    """Return the most-clicked documents for a query over a look-back window.

    Data is read from
    :class:`~icv_search.models.click_tracking.SearchClickAggregate`.  CTR per
    document is calculated using
    :class:`~icv_search.models.aggregates.SearchQueryAggregate` totals for the
    same window.  The query string is normalised (stripped and lowercased)
    before matching.

    Args:
        index_name: Logical name of the search index.
        query: The search query string to analyse.
        days: Look-back window in days.
        limit: Maximum number of documents to return.
        tenant_id: Restrict results to a specific tenant.

    Returns:
        List of dicts ordered by ``click_count`` descending, each with:

        - ``document_id`` (str): The clicked document identifier.
        - ``click_count`` (int): Total clicks in the window.
        - ``ctr`` (float): Click-through rate for this document (0.0 – 1.0).
    """
    from icv_search.models.aggregates import SearchQueryAggregate
    from icv_search.models.click_tracking import SearchClickAggregate

    normalised = query.strip().lower()
    since = timezone.now().date() - timedelta(days=days)

    click_qs = SearchClickAggregate.objects.filter(
        index_name=index_name,
        query=normalised,
        date__gte=since,
    )
    if tenant_id:
        click_qs = click_qs.filter(tenant_id=tenant_id)

    rows = click_qs.values("document_id").annotate(click_count=Sum("click_count")).order_by("-click_count")[:limit]

    if not rows:
        return []

    search_qs = SearchQueryAggregate.objects.filter(
        index_name=index_name,
        query=normalised,
        date__gte=since,
    )
    if tenant_id:
        search_qs = search_qs.filter(tenant_id=tenant_id)

    total_searches = search_qs.aggregate(total=Sum("total_count"))["total"] or 0

    result = []
    for row in rows:
        click_count = row["click_count"] or 0
        ctr = (click_count / total_searches) if total_searches > 0 else 0.0
        result.append(
            {
                "document_id": row["document_id"],
                "click_count": click_count,
                "ctr": ctr,
            }
        )

    return result
