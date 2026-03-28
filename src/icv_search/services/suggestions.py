"""Search suggestion service functions.

Leverages existing SearchQueryAggregate data to provide trending and
typeahead suggestions without requiring an external service.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


def get_trending_searches(
    index_name: str,
    *,
    days: int = 1,
    limit: int = 10,
    tenant_id: str = "",
) -> list[dict]:
    """Return trending search queries for a given index.

    Queries are ranked by total search count within the look-back window.

    Args:
        index_name: Logical name of the search index.
        days: Look-back window in days (default 1 for "today's trends").
        limit: Maximum number of results to return.
        tenant_id: Restrict to a specific tenant when provided.

    Returns:
        List of dicts with ``query`` and ``count`` keys, ordered by count
        descending.
    """
    from icv_search.models.aggregates import SearchQueryAggregate

    since = timezone.now().date() - timedelta(days=days)
    qs = SearchQueryAggregate.objects.filter(
        index_name=index_name,
        date__gte=since,
    )

    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)

    return list(qs.values("query").annotate(count=Sum("total_count")).order_by("-count")[:limit])


def get_suggested_queries(
    index_name: str,
    partial: str,
    *,
    limit: int = 5,
    tenant_id: str = "",
) -> list[dict]:
    """Return typeahead suggestions matching a partial query string.

    Searches existing aggregate data for queries that start with the given
    partial string, ranked by popularity over the last 30 days.

    Args:
        index_name: Logical name of the search index.
        partial: The partial query string to match (prefix match).
        limit: Maximum number of suggestions to return.
        tenant_id: Restrict to a specific tenant when provided.

    Returns:
        List of dicts with ``query`` and ``count`` keys, ordered by count
        descending. Returns an empty list when ``partial`` is blank.
    """
    from icv_search.models.aggregates import SearchQueryAggregate

    normalised = partial.strip().lower()
    if not normalised:
        return []

    # Look back 30 days for suggestion data.
    since = timezone.now().date() - timedelta(days=30)
    qs = SearchQueryAggregate.objects.filter(
        index_name=index_name,
        query__startswith=normalised,
        date__gte=since,
    )

    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)

    return list(qs.values("query").annotate(count=Sum("total_count")).order_by("-count")[:limit])
