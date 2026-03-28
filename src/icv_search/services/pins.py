"""Search pin service functions."""

from __future__ import annotations

import logging

from icv_search.types import SearchResult

logger = logging.getLogger(__name__)


def get_pins_for_query(
    index_name: str,
    query: str,
    tenant_id: str = "",
) -> list:
    """Return all active SearchPin instances matching the query, ordered by position.

    Pins with a normal position (>= 0) come first sorted by position ascending.
    Pins with position ``-1`` (bury) are appended at the end.

    Args:
        index_name: Logical search index name to scope the rule lookup.
        query: The user's search query string.
        tenant_id: Optional tenant identifier. Blank matches global rules only.

    Returns:
        List of matching :class:`~icv_search.models.merchandising.SearchPin`
        instances, sorted so that pinned positions are applied in order.
    """
    from icv_search.merchandising_cache import get_matching_rules
    from icv_search.models.merchandising import SearchPin

    pins = get_matching_rules(
        SearchPin,
        "SearchPin",
        index_name,
        query,
        tenant_id,
        single_winner=False,
    )
    # Sort by position ascending, with -1 (bury) at the end.
    return sorted(pins, key=lambda p: (p.position == -1, p.position))


def apply_pins(
    result: SearchResult,
    pins: list,
    index_name: str = "",
    tenant_id: str = "",
) -> SearchResult:
    """Apply pin rules to a SearchResult, inserting/moving pinned documents.

    Pinned documents are placed at their configured positions:

    - Position >= 0: insert at that zero-based index.
    - Position -1: push to the end (bury).

    If a pinned document already exists in the results it is moved to the
    target position. If it does not exist, a stub document containing only the
    ID (and ``_pinned: True``) is inserted; the consuming application is
    responsible for enriching it.

    The ``estimated_total_hits`` is incremented only when stub documents are
    added (i.e. the document was not already present in the result set).

    Args:
        result: The :class:`~icv_search.types.SearchResult` to transform.
        pins: List of :class:`~icv_search.models.merchandising.SearchPin`
            instances, pre-sorted by position (as returned by
            :func:`get_pins_for_query`).
        index_name: Unused — reserved for future per-index enrichment hooks.
        tenant_id: Unused — reserved for future per-tenant enrichment hooks.

    Returns:
        A new :class:`~icv_search.types.SearchResult` with pins applied.
    """
    if not pins:
        return result

    hits = list(result.hits)  # shallow copy
    scores: list = list(result.ranking_scores) if result.ranking_scores else []
    added_count = 0

    for pin in pins:
        doc_id = pin.document_id

        # Locate an existing hit by document ID.
        existing_idx: int | None = None
        for i, hit in enumerate(hits):
            if str(hit.get("id", "")) == str(doc_id):
                existing_idx = i
                break

        # Extract or create the document.
        if existing_idx is not None:
            doc = hits.pop(existing_idx)
            score = scores.pop(existing_idx) if existing_idx < len(scores) else None
        else:
            # Stub document — the consuming application should enrich.
            doc = {"id": doc_id, "_pinned": True}
            score = None
            added_count += 1

        # Mark as pinned and optionally attach the editorial label.
        doc["_pinned"] = True
        if pin.label:
            doc["_pin_label"] = pin.label

        # Insert at the target position.
        if pin.position == -1:
            hits.append(doc)
            if scores:
                scores.append(score)
        else:
            pos = min(pin.position, len(hits))
            hits.insert(pos, doc)
            if scores:
                scores.insert(pos, score)

    return SearchResult(
        hits=hits,
        query=result.query,
        processing_time_ms=result.processing_time_ms,
        estimated_total_hits=result.estimated_total_hits + added_count,
        limit=result.limit,
        offset=result.offset,
        facet_distribution=result.facet_distribution,
        formatted_hits=result.formatted_hits,
        ranking_scores=scores,
        raw=result.raw,
    )
