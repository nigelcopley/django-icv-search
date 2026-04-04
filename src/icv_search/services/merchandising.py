"""Merchandised search pipeline — the 9-step orchestrator.

Composes redirect checks, query rewrites, search execution, pin insertion,
boost re-ranking, zero-result fallbacks, and banner attachment into a single
high-level entry point.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def merchandised_search(
    name_or_index: str,
    query: str,
    tenant_id: str = "",
    *,
    user: Any = None,
    metadata: dict[str, Any] | None = None,
    log_query: bool = True,
    skip_redirects: bool = False,
    skip_rewrites: bool = False,
    skip_preprocessing: bool = False,
    skip_pins: bool = False,
    skip_boosts: bool = False,
    skip_banners: bool = False,
    skip_fallbacks: bool = False,
    **params: Any,
) -> Any:
    """Execute a search with the full merchandising pipeline.

    The pipeline runs ten steps in order:

    1. **Feature gate** — if ``ICV_SEARCH_MERCHANDISING_ENABLED`` is ``False``,
       delegate to ``search()`` and wrap in a ``MerchandisedSearchResult``.
    2. **Normalise** the query.
    1.5. **Preprocess** — run the query preprocessor to extract intent,
       filters, sort, and handle preprocessor-driven redirects or skip_search
       (runs after normalisation, before the redirect check).
    3. **Redirect check** — short-circuit with a redirect if matched.
    4. **Rewrite** — transparently rewrite the query and merge filters/sort.
    5. **Search** — execute the backend search.
    6. **Pins** — insert or move pinned documents.
    7. **Boosts** — adjust ranking scores and re-sort.
    8. **Fallback** — when zero results, execute fallback strategy.
    9. **Banners** — attach matching banners.

    Each step can be individually skipped via its ``skip_*`` parameter.

    Args:
        name_or_index: Index name or SearchIndex instance.
        query: The user's search query.
        tenant_id: Tenant identifier.
        user: Optional user for analytics logging.
        metadata: Optional metadata dict for query logging.
        log_query: Whether to create a ``SearchQueryLog`` entry.  Pass
            ``False`` for system-generated searches (category browse,
            trending products, dynamic filter pages) that should not
            pollute search analytics.  Defaults to ``True``.
        skip_redirects: Skip the redirect check step.
        skip_rewrites: Skip the rewrite step.
        skip_preprocessing: Skip the query preprocessing step.
        skip_pins: Skip the pin insertion step.
        skip_boosts: Skip the boost re-ranking step.
        skip_banners: Skip the banner attachment step.
        skip_fallbacks: Skip the zero-result fallback step.
        **params: Additional search parameters (limit, offset, filter, sort, etc.).

    Returns:
        A :class:`~icv_search.types.MerchandisedSearchResult` with all
        merchandising metadata attached.
    """
    from icv_search.merchandising_cache import normalise_query
    from icv_search.services.banners import get_banners_for_query
    from icv_search.services.boosts import apply_boosts, get_boost_rules_for_query
    from icv_search.services.fallbacks import execute_fallback, get_fallback_for_query
    from icv_search.services.pins import apply_pins, get_pins_for_query
    from icv_search.services.redirects import check_redirect, resolve_redirect_url
    from icv_search.services.rewrites import apply_rewrite
    from icv_search.services.search import search
    from icv_search.types import MerchandisedSearchResult, SearchResult

    applied_rules: list[dict[str, Any]] = []
    original_query = query
    was_rewritten = False
    preprocessed = None

    # Step 1: Feature gate
    if not _is_merchandising_enabled():
        result = search(name_or_index, query, tenant_id, user=user, metadata=metadata, log_query=log_query, **params)
        return MerchandisedSearchResult.from_search_result(
            result,
            original_query=query,
        )

    # Step 2: Normalise query
    normalised = normalise_query(query)

    # Step 1.5: Preprocess query
    if not skip_preprocessing:
        from icv_search.services.preprocessing import preprocess

        preprocessed_result = preprocess(
            normalised,
            index_name=name_or_index if isinstance(name_or_index, str) else name_or_index.name,
            tenant_id=tenant_id,
            user=user,
            metadata=metadata,
        )
        preprocessed = preprocessed_result

        # Record preprocessing in applied_rules (BR-029)
        applied_rules.append(
            {
                "type": "preprocess",
                "intent": preprocessed_result.intent,
                "confidence": preprocessed_result.confidence,
                "filters_extracted": preprocessed_result.extracted_filters,
                "sort_extracted": preprocessed_result.extracted_sort,
                "metadata": preprocessed_result.metadata,
            }
        )

        # Handle preprocessor redirect (takes precedence over skip_search)
        if preprocessed_result.redirect_url:
            return MerchandisedSearchResult(
                redirect={"url": preprocessed_result.redirect_url, "status": 302, "type": "preprocess"},
                original_query=original_query,
                applied_rules=applied_rules,
                query=normalised,
                preprocessed=preprocessed,
                detected_intent=preprocessed_result.intent,
            )

        # Handle skip_search
        if preprocessed_result.skip_search:
            return MerchandisedSearchResult(
                original_query=original_query,
                applied_rules=applied_rules,
                query=normalised,
                preprocessed=preprocessed,
                detected_intent=preprocessed_result.intent,
            )

        # Use the preprocessed query for remaining pipeline steps
        normalised = preprocessed_result.query

        # Merge preprocessor filters with caller filters (BR-028)
        # Caller filters take precedence over preprocessor filters
        if preprocessed_result.extracted_filters:
            existing_filter = params.get("filter")
            if existing_filter and isinstance(existing_filter, dict):
                merged = {**preprocessed_result.extracted_filters, **existing_filter}
            else:
                merged = preprocessed_result.extracted_filters
            params = {**params, "filter": merged}

        # Merge preprocessor sort
        if preprocessed_result.extracted_sort:
            existing_sort = params.get("sort", [])
            if isinstance(existing_sort, str):
                existing_sort = [existing_sort]
            params = {**params, "sort": preprocessed_result.extracted_sort + list(existing_sort)}

    # Step 3: Redirect check
    if not skip_redirects:
        redirect = check_redirect(
            name_or_index if isinstance(name_or_index, str) else name_or_index.name, normalised, tenant_id
        )
        if redirect is not None:
            url = resolve_redirect_url(redirect, query)
            applied_rules.append(
                {
                    "type": "redirect",
                    "rule_id": str(redirect.pk),
                    "destination_url": url,
                }
            )
            return MerchandisedSearchResult(
                redirect={"url": url, "status": redirect.http_status, "type": redirect.destination_type},
                original_query=original_query,
                applied_rules=applied_rules,
                query=normalised,
            )

    # Step 4: Rewrite
    search_query = normalised
    if not skip_rewrites:
        index_name_str = name_or_index if isinstance(name_or_index, str) else name_or_index.name
        rewritten, filters, sort, rewrite_rule = apply_rewrite(index_name_str, normalised, tenant_id)
        if rewrite_rule is not None:
            search_query = rewritten
            was_rewritten = True
            applied_rules.append(
                {
                    "type": "rewrite",
                    "rule_id": str(rewrite_rule.pk),
                    "original_query": normalised,
                    "rewritten_query": rewritten,
                }
            )
            # Merge or replace filters
            if filters:
                if rewrite_rule.merge_filters:
                    existing_filter = params.get("filter")
                    if existing_filter and isinstance(existing_filter, dict):
                        merged = {**existing_filter, **filters}
                    else:
                        merged = filters
                    params = {**params, "filter": merged}
                else:
                    params = {**params, "filter": filters}
            if sort:
                params = {**params, "sort": sort}

    # Step 5: Execute search
    result = search(name_or_index, search_query, tenant_id, user=user, metadata=metadata, log_query=log_query, **params)

    # Step 6: Apply pins
    if not skip_pins:
        index_name_str = name_or_index if isinstance(name_or_index, str) else name_or_index.name
        pins = get_pins_for_query(index_name_str, normalised, tenant_id)
        if pins:
            result = apply_pins(result, pins, index_name_str, tenant_id)
            for pin in pins:
                applied_rules.append(
                    {
                        "type": "pin",
                        "rule_id": str(pin.pk),
                        "document_id": pin.document_id,
                        "position": pin.position,
                    }
                )

    # Step 7: Apply boosts
    if not skip_boosts:
        index_name_str = name_or_index if isinstance(name_or_index, str) else name_or_index.name
        boost_rules = get_boost_rules_for_query(index_name_str, normalised, tenant_id)
        if boost_rules:
            result = apply_boosts(result, boost_rules)
            for rule in boost_rules:
                applied_rules.append(
                    {
                        "type": "boost",
                        "rule_id": str(rule.pk),
                        "field": rule.field,
                        "boost_weight": str(rule.boost_weight),
                    }
                )

    # Step 8: Zero-result fallback
    is_fallback = False
    if not skip_fallbacks and not result.hits and result.estimated_total_hits == 0:
        index_name_str = name_or_index if isinstance(name_or_index, str) else name_or_index.name
        fallback = get_fallback_for_query(index_name_str, normalised, tenant_id)
        if fallback is not None:
            applied_rules.append(
                {
                    "type": "fallback",
                    "rule_id": str(fallback.pk),
                    "fallback_type": fallback.fallback_type,
                }
            )
            fallback_result = execute_fallback(fallback, index_name_str, original_query, tenant_id, **params)
            if isinstance(fallback_result, str):
                # Redirect fallback
                return MerchandisedSearchResult(
                    redirect={"url": fallback_result, "status": 302, "type": "fallback"},
                    original_query=original_query,
                    applied_rules=applied_rules,
                    query=search_query,
                    was_rewritten=was_rewritten,
                    is_fallback=True,
                )
            # Search-based fallback — use its result
            result = SearchResult(
                hits=fallback_result.hits,
                query=fallback_result.query,
                processing_time_ms=fallback_result.processing_time_ms,
                estimated_total_hits=fallback_result.estimated_total_hits,
                limit=fallback_result.limit,
                offset=fallback_result.offset,
                facet_distribution=fallback_result.facet_distribution,
                formatted_hits=fallback_result.formatted_hits,
                ranking_scores=fallback_result.ranking_scores,
                raw=fallback_result.raw,
            )
            is_fallback = True

    # Step 9: Attach banners
    banners: list[dict[str, Any]] = []
    if not skip_banners:
        index_name_str = name_or_index if isinstance(name_or_index, str) else name_or_index.name
        banner_rules = get_banners_for_query(index_name_str, normalised, tenant_id)
        for banner in banner_rules:
            banners.append(
                {
                    "title": banner.title,
                    "content": banner.content,
                    "image_url": banner.image_url,
                    "link_url": banner.link_url,
                    "link_text": banner.link_text,
                    "position": banner.position,
                    "banner_type": banner.banner_type,
                    "metadata": banner.metadata,
                }
            )
            applied_rules.append(
                {
                    "type": "banner",
                    "rule_id": str(banner.pk),
                    "title": banner.title,
                }
            )

    return MerchandisedSearchResult.from_search_result(
        result,
        banners=banners,
        applied_rules=applied_rules,
        original_query=original_query,
        was_rewritten=was_rewritten,
        is_fallback=is_fallback,
        preprocessed=preprocessed,
        detected_intent=preprocessed.intent if preprocessed is not None else "",
    )


def _is_merchandising_enabled() -> bool:
    """Read the merchandising feature gate at call time."""
    from django.conf import settings

    return getattr(settings, "ICV_SEARCH_MERCHANDISING_ENABLED", False)
