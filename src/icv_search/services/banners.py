"""Search banner service functions."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_banners_for_query(
    index_name: str,
    query: str,
    tenant_id: str = "",
) -> list:
    """Return all active SearchBanner instances matching the query.

    Looks up active, in-schedule ``SearchBanner`` rules for the given index and
    tenant. Results are ordered by priority (highest first), then by creation
    date for consistent rendering order.

    Args:
        index_name: Logical search index name to scope the rule lookup.
        query: The user's search query string.
        tenant_id: Optional tenant identifier. Blank matches global rules only.

    Returns:
        List of matching ``SearchBanner`` instances (may be empty).
    """
    from icv_search.merchandising_cache import get_matching_rules
    from icv_search.models.merchandising import SearchBanner

    banners = get_matching_rules(
        SearchBanner,
        "SearchBanner",
        index_name,
        query,
        tenant_id,
        single_winner=False,
    )
    return banners
