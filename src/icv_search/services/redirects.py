"""Query redirect service functions."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)


def check_redirect(
    index_name: str,
    query: str,
    tenant_id: str = "",
) -> Any | None:
    """Check if a query should be redirected.

    Looks up active, in-schedule ``QueryRedirect`` rules for the given index and
    tenant. Returns the highest-priority matching rule, or ``None`` when no rule
    matches.

    Args:
        index_name: Logical search index name to scope the rule lookup.
        query: The user's search query string.
        tenant_id: Optional tenant identifier. Blank matches global rules only.

    Returns:
        The highest-priority matching ``QueryRedirect`` instance, or ``None``.
    """
    from icv_search.merchandising_cache import get_matching_rules
    from icv_search.models.merchandising import QueryRedirect

    matches = get_matching_rules(
        QueryRedirect,
        "QueryRedirect",
        index_name,
        query,
        tenant_id,
        single_winner=True,
    )
    return matches[0] if matches else None


def resolve_redirect_url(redirect: Any, query: str) -> str:
    """Build the final redirect URL, optionally appending the original query.

    When ``redirect.preserve_query`` is ``True`` the original search query is
    appended as a ``q`` parameter. Any existing ``q`` parameter in the
    destination URL is replaced.

    Args:
        redirect: A ``QueryRedirect`` model instance.
        query: The original search query string.

    Returns:
        The final redirect URL as a string.
    """
    url = redirect.destination_url
    if redirect.preserve_query and query:
        parsed = urlparse(url)
        existing_params = parse_qs(parsed.query)
        existing_params["q"] = [query]
        new_query = urlencode(existing_params, doseq=True)
        url = urlunparse(parsed._replace(query=new_query))
    return url
