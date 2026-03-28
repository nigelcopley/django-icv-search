"""Zero-result fallback service functions."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_fallback_for_query(
    index_name: str,
    query: str,
    tenant_id: str = "",
) -> Any | None:
    """Return the highest-priority ZeroResultFallback matching the query, or None.

    Looks up active, in-schedule ``ZeroResultFallback`` rules for the given
    index and tenant. Only the single highest-priority matching rule is
    returned — there is no cascading.

    Args:
        index_name: Logical search index name to scope the rule lookup.
        query: The user's search query string.
        tenant_id: Optional tenant identifier. Blank matches global rules only.

    Returns:
        The highest-priority matching ``ZeroResultFallback`` instance, or ``None``.
    """
    from icv_search.merchandising_cache import get_matching_rules
    from icv_search.models.merchandising import ZeroResultFallback

    matches = get_matching_rules(
        ZeroResultFallback,
        "ZeroResultFallback",
        index_name,
        query,
        tenant_id,
        single_winner=True,
    )
    return matches[0] if matches else None


def execute_fallback(
    fallback: Any,
    index_name: str,
    query: str,
    tenant_id: str = "",
    **search_params: Any,
) -> Any:
    """Execute a fallback strategy and return either a redirect URL or a MerchandisedSearchResult.

    Dispatches on ``fallback.fallback_type``:

    - ``redirect``: Returns the redirect URL as a string.
    - ``alternative_query``: Executes a search with the fallback query.
      Retries up to ``fallback.max_retries`` times, dropping the last word of
      the alternative query on each retry when the alternative also returns
      zero results.
    - ``curated_results``: Searches for specific document IDs supplied as a
      comma-separated list in ``fallback.fallback_value``.
    - ``popular_in_category``: Searches with a category filter derived from
      ``fallback.fallback_value`` (overridden by ``fallback.fallback_filters``
      when set).

    For all search-based fallback types the return value is a
    ``MerchandisedSearchResult`` with ``is_fallback=True`` and
    ``original_query`` set to the caller's original query.

    Args:
        fallback: A ``ZeroResultFallback`` model instance.
        index_name: Logical search index name.
        query: The original (zero-result) search query string.
        tenant_id: Optional tenant identifier.
        **search_params: Additional parameters forwarded to the search backend
            (limit, offset, sort, etc.).

    Returns:
        A redirect URL string for ``redirect`` type, or a
        ``MerchandisedSearchResult`` for all other types.
    """
    from icv_search.services.search import search
    from icv_search.types import MerchandisedSearchResult, SearchResult

    if fallback.fallback_type == "redirect":
        return fallback.fallback_value

    if fallback.fallback_type == "alternative_query":
        alt_query = fallback.fallback_value
        filters = fallback.fallback_filters if fallback.fallback_filters else {}
        merged_params = {**search_params}
        if filters:
            merged_params["filter"] = filters

        result = search(index_name, alt_query, tenant_id, **merged_params)

        # Retry logic: if the alternative also returns zero results, drop the
        # last word of the query and try again (up to max_retries - 1 times).
        retries = 0
        while not result.hits and retries < fallback.max_retries - 1:
            words = alt_query.split()
            if len(words) <= 1:
                break
            alt_query = " ".join(words[:-1])
            result = search(index_name, alt_query, tenant_id, **merged_params)
            retries += 1

        return MerchandisedSearchResult.from_search_result(
            result,
            original_query=query,
            is_fallback=True,
        )

    if fallback.fallback_type == "curated_results":
        # Parse comma-separated document IDs and search for them via a filter.
        doc_ids = [d.strip() for d in fallback.fallback_value.split(",") if d.strip()]
        if doc_ids:
            # Use the cross-backend dict filter format (list value = IN filter).
            merged_params = {**search_params, "filter": {"id": doc_ids}}
            result = search(index_name, "", tenant_id, **merged_params)
        else:
            result = SearchResult()

        return MerchandisedSearchResult.from_search_result(
            result,
            original_query=query,
            is_fallback=True,
        )

    if fallback.fallback_type == "popular_in_category":
        category = fallback.fallback_value
        filters = fallback.fallback_filters if fallback.fallback_filters else {}
        if not filters:
            filters = {"category": category}
        merged_params = {**search_params, "filter": filters}
        result = search(index_name, "", tenant_id, **merged_params)

        return MerchandisedSearchResult.from_search_result(
            result,
            original_query=query,
            is_fallback=True,
        )

    # Unknown fallback type — return an empty result with the fallback flag set.
    logger.warning(
        "Unknown fallback type %r for index %r; returning empty result.",
        fallback.fallback_type,
        index_name,
    )
    return MerchandisedSearchResult.from_search_result(
        SearchResult(),
        original_query=query,
        is_fallback=True,
    )
