"""Query preprocessor hook service."""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

_UNLOADED = object()
_preprocessor_callable: Any = _UNLOADED


def load_preprocessor() -> Any | None:
    """Load and cache the query preprocessor callable.

    Returns the callable, or ``None`` when ``ICV_SEARCH_QUERY_PREPROCESSOR``
    is empty. Raises ``ImproperlyConfigured`` when the dotted path cannot be
    imported (BR-026).
    """
    global _preprocessor_callable

    from django.conf import settings as django_settings

    path = getattr(django_settings, "ICV_SEARCH_QUERY_PREPROCESSOR", "")
    if not path:
        _preprocessor_callable = None
        return None

    try:
        from django.utils.module_loading import import_string

        callable_ = import_string(path)
    except ImportError as exc:
        raise ImproperlyConfigured(
            f"ICV_SEARCH_QUERY_PREPROCESSOR setting '{path}' could not be imported: {exc}"
        ) from exc

    _preprocessor_callable = callable_
    return callable_


def preprocess(
    query: str,
    index_name: str,
    tenant_id: str = "",
    *,
    user: Any | None = None,
    metadata: dict | None = None,
) -> Any:
    """Run the query through the configured preprocessor, if any.

    When no preprocessor is configured, returns the query unchanged. When the
    preprocessor raises, the failure is logged at WARNING level and the
    original query is returned unchanged — search is never broken by a
    failing preprocessor (BR-027).

    Args:
        query: The normalised query string.
        index_name: Logical search index name.
        tenant_id: Tenant identifier.
        user: Authenticated user, if available.
        metadata: Caller-supplied context dict.

    Returns:
        A :class:`~icv_search.types.PreprocessedQuery` instance.
    """
    global _preprocessor_callable

    from icv_search.types import PreprocessedQuery, QueryContext

    if _preprocessor_callable is _UNLOADED:
        load_preprocessor()

    if _preprocessor_callable is None:
        return PreprocessedQuery(query=query)

    context = QueryContext(
        index_name=index_name,
        tenant_id=tenant_id,
        original_query=query,
        user=user,
        metadata=metadata or {},
    )

    try:
        result = _preprocessor_callable(query, context)
    except Exception:
        logger.warning(
            "Query preprocessor failed for query '%s' in index '%s'. Falling back to original query.",
            query,
            index_name,
            exc_info=True,
        )
        return PreprocessedQuery(query=query)

    return result


def reset_preprocessor() -> None:
    """Reset the cached preprocessor callable. Used in tests."""
    global _preprocessor_callable
    _preprocessor_callable = _UNLOADED
