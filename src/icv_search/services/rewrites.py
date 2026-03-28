"""Query rewrite service functions."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def apply_rewrite(
    index_name: str,
    query: str,
    tenant_id: str = "",
) -> tuple[str, dict, list, Any | None]:
    """Check if a query should be rewritten and return the result.

    Looks up active, in-schedule ``QueryRewrite`` rules for the given index and
    tenant. Only the single highest-priority matching rewrite is applied — there
    is no cascading.

    Args:
        index_name: Logical search index name to scope the rule lookup.
        query: The user's original search query string.
        tenant_id: Optional tenant identifier. Blank matches global rules only.

    Returns:
        A 4-tuple of:

        - ``rewritten_query`` (str): The new query string, or the original if
          no rewrite matched.
        - ``filters`` (dict): Filters to inject into the search request, or
          an empty dict.
        - ``sort`` (list): Sort order to inject into the search request, or
          an empty list.
        - ``rule`` (QueryRewrite | None): The matched rule instance, or
          ``None`` when no rewrite applies.
    """
    from icv_search.merchandising_cache import get_matching_rules
    from icv_search.models.merchandising import QueryRewrite

    matches = get_matching_rules(
        QueryRewrite,
        "QueryRewrite",
        index_name,
        query,
        tenant_id,
        single_winner=True,
    )
    if not matches:
        return query, {}, [], None

    rule = matches[0]
    rewritten = rule.rewritten_query
    filters = rule.apply_filters if rule.apply_filters else {}
    sort = rule.apply_sort if rule.apply_sort else []
    return rewritten, filters, sort, rule
