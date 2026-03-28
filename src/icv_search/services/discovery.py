"""Discovery service functions — facet search and similar documents."""

from __future__ import annotations

from typing import Any

from icv_search.backends import get_search_backend
from icv_search.models import SearchIndex
from icv_search.services._utils import resolve_index
from icv_search.types import SearchResult


def facet_search(
    name_or_index: str | SearchIndex,
    facet_name: str,
    facet_query: str = "",
    tenant_id: str = "",
    **params: Any,
) -> list[dict[str, Any]]:
    """Search within facet values for typeahead in filter UIs.

    Returns a list of ``{"value": str, "count": int}`` dicts sorted by
    count descending.

    Args:
        name_or_index: Index name or SearchIndex instance.
        facet_name: Name of the facet/filterable field to search.
        facet_query: Partial text to match against facet values.
        tenant_id: Tenant identifier (only needed if passing a name).

    Returns:
        Facet values with counts, sorted by count descending.
    """
    index = resolve_index(name_or_index, tenant_id)
    backend = get_search_backend()
    return backend.facet_search(
        uid=index.engine_uid,
        facet_name=facet_name,
        facet_query=facet_query,
        **params,
    )


def similar_documents(
    name_or_index: str | SearchIndex,
    document_id: str,
    tenant_id: str = "",
    **params: Any,
) -> SearchResult:
    """Find documents similar to a given document.

    Uses the engine's native similarity/more-like-this feature.

    Args:
        name_or_index: Index name or SearchIndex instance.
        document_id: Primary key of the source document.
        tenant_id: Tenant identifier (only needed if passing a name).

    Returns:
        SearchResult containing similar documents.
    """
    index = resolve_index(name_or_index, tenant_id)
    backend = get_search_backend()
    raw = backend.similar_documents(
        uid=index.engine_uid,
        document_id=document_id,
        **params,
    )
    return SearchResult.from_engine(raw)
