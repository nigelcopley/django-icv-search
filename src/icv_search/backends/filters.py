"""Filter and sort translation utilities for search backends.

Provides a Django-native dict/list API for filters and sorts that
backends can translate into their engine-specific format.

Django-native filter dict::

    {"city": "Madrid", "is_active": True, "price": 150}
    {"category": ["equipment", "accessories"]}  # IN filter

Django-native sort list::

    ["-created_at", "name"]  # - prefix = descending

Meilisearch filter string::

    "city = 'Madrid' AND is_active = true AND price = 150"
    "category IN ['equipment', 'accessories']"

Meilisearch sort list::

    ["created_at:desc", "name:asc"]

Solr filter query list (fq)::

    ["city:Madrid", "is_active:true", "price:150"]

Solr sort string::

    "price desc, name asc"
"""

from __future__ import annotations

import math
from typing import Any


def _meili_quote(value: str) -> str:
    """Escape a value for Meilisearch filter single-quoted strings."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


# Mean Earth radius in metres (WGS-84 approximation).
_EARTH_RADIUS_M: float = 6_371_000.0

# Operator suffix mapping for Django-style range lookups.
_RANGE_OPERATORS: dict[str, str] = {
    "__gte": ">=",
    "__gt": ">",
    "__lte": "<=",
    "__lt": "<",
}


def translate_filter_to_meilisearch(filters: dict[str, Any] | str) -> str:
    """Convert a Django-native filter dict to a Meilisearch filter string.

    Passes through strings unchanged (for backwards compatibility).

    Args:
        filters: Either a dict of field:value pairs or a raw Meilisearch
            filter string.

    Returns:
        A Meilisearch-compatible filter string.
    """
    if isinstance(filters, str):
        return filters

    if not isinstance(filters, dict) or not filters:
        return ""

    parts = []
    for field, value in filters.items():
        # Check for range lookup suffixes (e.g. price__gte, created_at__lt).
        range_op: str | None = None
        real_field = field
        for suffix, op in _RANGE_OPERATORS.items():
            if field.endswith(suffix):
                real_field = field[: -len(suffix)]
                range_op = op
                break

        if range_op is not None:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                parts.append(f"{real_field} {range_op} {value}")
            # Non-numeric range values are silently skipped.
        elif isinstance(value, bool):
            parts.append(f"{field} = {str(value).lower()}")
        elif isinstance(value, (int, float)):
            parts.append(f"{field} = {value}")
        elif isinstance(value, list):
            formatted = ", ".join(f"'{_meili_quote(str(v))}'" if isinstance(v, str) else str(v) for v in value)
            parts.append(f"{field} IN [{formatted}]")
        elif value is None:
            parts.append(f"{field} IS NULL")
        else:
            parts.append(f"{field} = '{_meili_quote(str(value))}'")

    return " AND ".join(parts)


def translate_sort_to_meilisearch(sort: list[str] | str) -> list[str]:
    """Convert a Django-native sort list to Meilisearch sort format.

    Passes through strings and already-formatted lists unchanged.

    Args:
        sort: Either a list of field names (with optional - prefix for
            descending) or a Meilisearch-formatted sort list.

    Returns:
        A list of Meilisearch-compatible sort strings.
    """
    if isinstance(sort, str):
        return [sort] if sort else []

    if not isinstance(sort, list) or not sort:
        return []

    result = []
    for field in sort:
        if ":" in field:
            # Already in Meilisearch format (e.g. "price:desc")
            result.append(field)
        elif field.startswith("-"):
            result.append(f"{field[1:]}:desc")
        else:
            result.append(f"{field}:asc")

    return result


def apply_filters_to_documents(
    documents: list[dict[str, Any]],
    filters: dict[str, Any] | str,
) -> list[dict[str, Any]]:
    """Apply Django-native filters to an in-memory document list.

    Used by DummyBackend and PostgresBackend for filtering without an
    external engine.

    Args:
        documents: List of document dicts.
        filters: Filter dict or string.

    Returns:
        Filtered list of documents.
    """
    if isinstance(filters, str) or not filters:
        return documents

    result = []
    for doc in documents:
        if _matches_filters(doc, filters):
            result.append(doc)
    return result


def _matches_filters(doc: dict[str, Any], filters: dict[str, Any]) -> bool:
    """Check if a document matches all filter conditions."""
    for field, value in filters.items():
        # Check for range lookup suffixes (e.g. price__gte, created_at__lt).
        range_op: str | None = None
        real_field = field
        for suffix, op in _RANGE_OPERATORS.items():
            if field.endswith(suffix):
                real_field = field[: -len(suffix)]
                range_op = op
                break

        if range_op is not None:
            # Range comparisons only apply to numeric values.
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            doc_value = doc.get(real_field)
            try:
                doc_num = float(doc_value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return False
            if (
                range_op == ">="
                and not (doc_num >= value)
                or range_op == ">"
                and not (doc_num > value)
                or range_op == "<="
                and not (doc_num <= value)
                or range_op == "<"
                and not (doc_num < value)
            ):
                return False
            continue

        doc_value = doc.get(field)

        if isinstance(value, list):
            # IN filter
            if doc_value not in value and str(doc_value) not in [str(v) for v in value]:
                return False
        elif isinstance(value, bool):
            if bool(doc_value) != value:
                return False
        elif isinstance(value, (int, float)):
            try:
                if float(doc_value) != float(value):
                    return False
            except (TypeError, ValueError):
                return False
        elif value is None:
            if doc_value is not None:
                return False
        else:
            if str(doc_value) != str(value):
                return False

    return True


def apply_sort_to_documents(
    documents: list[dict[str, Any]],
    sort: list[str],
) -> list[dict[str, Any]]:
    """Apply Django-native sort to an in-memory document list.

    Args:
        documents: List of document dicts.
        sort: List of field names with optional - prefix.

    Returns:
        Sorted list of documents.
    """
    if not sort:
        return documents

    # Build sort keys in reverse order (last sort field has lowest priority)
    result = list(documents)
    for field in reversed(sort):
        if field.startswith("-"):
            field_name = field[1:]
            reverse = True
        elif ":" in field:
            # Meilisearch format
            parts = field.split(":")
            field_name = parts[0]
            reverse = parts[1] == "desc"
        else:
            field_name = field
            reverse = False

        result.sort(key=lambda doc, f=field_name: _sort_key(doc.get(f)), reverse=reverse)

    return result


def _sort_key(value: Any) -> tuple:
    """Generate a sort key that handles mixed types and None values."""
    if value is None:
        return (1, "")  # None values sort last
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (0, value)
    return (0, str(value))


def _haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate the great-circle distance between two points in metres.

    Uses the Haversine formula with a spherical Earth model (mean radius
    6,371 km). Accurate to within ~0.5 % for most practical distances.

    Args:
        lat1: Latitude of the first point in decimal degrees.
        lng1: Longitude of the first point in decimal degrees.
        lat2: Latitude of the second point in decimal degrees.
        lng2: Longitude of the second point in decimal degrees.

    Returns:
        Distance in metres.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return _EARTH_RADIUS_M * c


# ---------------------------------------------------------------------------
# Solr filter and sort translation
# ---------------------------------------------------------------------------

# Operator suffix mapping for Solr range query syntax.
# Inclusive brackets [ ] vs exclusive braces { } follow Solr convention.
_SOLR_RANGE_OPERATORS: dict[str, tuple[str, str, str, str]] = {
    # suffix: (open_bracket, placeholder_low, placeholder_high, close_bracket)
    "__gte": ("[", "{value}", "*", "]"),  # [value TO *]
    "__gt": ("{", "{value}", "*", "}"),  # {value TO *}
    "__lte": ("[", "*", "{value}", "]"),  # [* TO value]
    "__lt": ("[", "*", "{value}", "}"),  # [* TO value}
}


SOLR_SPECIAL = (" ", ":", '"', "'", "(", ")", "[", "]", "{", "}")


def _solr_quote(value: Any) -> str:
    """Return a Solr-safe representation of a scalar value.

    Strings containing whitespace or special characters are quoted with
    double-quotes. Embedded double-quotes and backslashes are escaped first.
    Booleans and numbers are returned as-is.
    """
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    if any(c in escaped for c in SOLR_SPECIAL):
        return f'"{escaped}"'
    return escaped


def translate_filter_to_solr(
    filters: dict[str, Any] | str | list[str],
) -> list[str]:
    """Convert a Django-native filter dict to a list of Solr ``fq`` strings.

    Returns a list so that each clause can be cached independently by
    Solr's filter-query cache.  Passes through strings and string lists
    unchanged (for callers already holding raw Solr ``fq`` clauses).

    Supported operators (via ``__`` suffix notation):

    * Equality (no suffix): ``{"city": "Madrid"}`` → ``["city:Madrid"]``
    * Boolean: ``{"is_active": True}`` → ``["is_active:true"]``
    * Numeric: ``{"price": 150}`` → ``["price:150"]``
    * IN list: ``{"cat": ["a", "b"]}`` → ``["cat:(a OR b)"]``
    * Range ``__gte``: ``{"price__gte": 10}`` → ``["price:[10 TO *]"]``
    * Range ``__gt``:  ``{"price__gt": 10}`` → ``["price:{10 TO *}"]``
    * Range ``__lte``: ``{"price__lte": 100}`` → ``["price:[* TO 100]"]``
    * Range ``__lt``:  ``{"price__lt": 100}`` → ``["price:[* TO 100}"]``
    * NULL check: ``{"field": None}`` → ``["-field:[* TO *]"]``
    """
    if isinstance(filters, str):
        return [filters] if filters else []
    if isinstance(filters, list):
        return filters

    if not isinstance(filters, dict) or not filters:
        return []

    parts: list[str] = []
    for field, value in filters.items():
        # Check for range lookup suffixes.
        matched_suffix: str | None = None
        real_field = field
        for suffix in _SOLR_RANGE_OPERATORS:
            if field.endswith(suffix):
                real_field = field[: -len(suffix)]
                matched_suffix = suffix
                break

        if matched_suffix is not None:
            open_b, low_tmpl, high_tmpl, close_b = _SOLR_RANGE_OPERATORS[matched_suffix]
            v_str = (
                str(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else _solr_quote(value)
            )
            low = v_str if low_tmpl == "{value}" else low_tmpl
            high = v_str if high_tmpl == "{value}" else high_tmpl
            parts.append(f"{real_field}:{open_b}{low} TO {high}{close_b}")
        elif value is None:
            parts.append(f"-{field}:[* TO *]")
        elif isinstance(value, list):
            members = " OR ".join(_solr_quote(v) for v in value)
            parts.append(f"{field}:({members})")
        else:
            parts.append(f"{field}:{_solr_quote(value)}")

    return parts


def translate_sort_to_solr(sort: list[str] | str) -> str:
    """Convert a Django-native sort list to a Solr ``sort`` parameter string.

    Passes through strings unchanged (for callers already holding a raw
    Solr sort string).

    Mapping rules:

    * ``["-price", "name"]`` → ``"price desc, name asc"``
    * ``["created_at"]`` → ``"created_at asc"``
    * ``["-score", "title"]`` → ``"score desc, title asc"``

    Args:
        sort: List of field names with optional ``-`` prefix for
            descending order, or a pre-formatted Solr sort string.

    Returns:
        A comma-separated Solr-compatible sort string, or ``""`` when
        the input is empty.
    """
    if isinstance(sort, str):
        return sort

    if not isinstance(sort, list) or not sort:
        return ""

    parts: list[str] = []
    for field in sort:
        if " " in field and ("asc" in field or "desc" in field):
            # Already in Solr format ("price desc")
            parts.append(field)
        elif field.startswith("-"):
            parts.append(f"{field[1:]} desc")
        else:
            parts.append(f"{field} asc")

    return ", ".join(parts)
