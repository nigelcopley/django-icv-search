"""Search intelligence service functions.

Provides demand signal extraction, query clustering, synonym suggestions, and
automatic rewrite creation derived from ``SearchQueryAggregate`` data.

Clustering and synonym functions require the ``pg_trgm`` PostgreSQL extension.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_min_volume_setting() -> int:
    """Return ``ICV_SEARCH_INTELLIGENCE_MIN_VOLUME`` (default 5)."""
    from django.conf import settings as django_settings

    return getattr(django_settings, "ICV_SEARCH_INTELLIGENCE_MIN_VOLUME", 5)


def _get_auto_synonym_confidence() -> float:
    """Return ``ICV_SEARCH_AUTO_SYNONYM_CONFIDENCE`` (default 0.8)."""
    from django.conf import settings as django_settings

    return getattr(django_settings, "ICV_SEARCH_AUTO_SYNONYM_CONFIDENCE", 0.8)


def _get_merchandising_enabled() -> bool:
    """Return ``ICV_SEARCH_MERCHANDISING_ENABLED`` (default False)."""
    from django.conf import settings as django_settings

    return getattr(django_settings, "ICV_SEARCH_MERCHANDISING_ENABLED", False)


def _check_pg_trgm() -> None:
    """Raise ``ImproperlyConfigured`` when the ``pg_trgm`` extension is absent."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
        row = cursor.fetchone()

    if not row:
        raise ImproperlyConfigured(
            "The pg_trgm PostgreSQL extension is required for query clustering. "
            "Install it with: CREATE EXTENSION pg_trgm;"
        )


# ---------------------------------------------------------------------------
# Union-Find for clustering
# ---------------------------------------------------------------------------


class _UnionFind:
    """Minimal union-find used to build query clusters from similar pairs."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        if x not in self._parent:
            self._parent[x] = x
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])  # path compression
        return self._parent[x]

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self._parent[ry] = rx


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


def get_demand_signals(
    index_name: str,
    days: int = 30,
    min_volume: int | None = None,
    min_gap_score: float = 0.0,
    exclude_patterns: list[str] | None = None,
    tenant_id: str = "",
) -> list[dict[str, Any]]:
    """Return queries ranked by demand signal strength.

    Demand signals identify high-volume, high-zero-result-rate queries — the
    strongest indicators of unmet demand in the search index.

    Args:
        index_name: Logical search index name to scope the query.
        days: Look-back window in days.
        min_volume: Minimum total query volume to include a query. When
            ``None``, reads from ``ICV_SEARCH_INTELLIGENCE_MIN_VOLUME``
            (default 5). The effective value is always at least 1 (BR-021).
        min_gap_score: Minimum gap score to include a query.
        exclude_patterns: List of Python regex strings. Queries matching any
            pattern are excluded. Applied via ``re.search()`` (case-sensitive).
        tenant_id: Restrict results to a specific tenant. Empty string returns
            results across all tenants.

    Returns:
        List of dicts ordered by ``gap_score`` descending, each with:

        - ``query`` (str): The query string.
        - ``volume`` (int): Total search count over the window.
        - ``zero_result_rate`` (float): Fraction of searches returning no hits.
        - ``gap_score`` (float): ``zero_result_rate * volume``.
        - ``trend`` (float): Week-over-week volume growth as a percentage.
          Positive means growing; 0.0 when there is no previous-week data.
        - ``ctr`` (float): Click-through rate (0.0 when no click data exists).
    """
    from icv_search.models.aggregates import SearchQueryAggregate
    from icv_search.models.click_tracking import SearchClickAggregate

    # Resolve min_volume from setting when not explicitly supplied (BR-021).
    if min_volume is None:
        min_volume = _get_min_volume_setting()
    min_volume = max(1, min_volume)

    now = timezone.now().date()
    window_start = now - timedelta(days=days)

    # --- Main aggregate: volume + zero-result sums per query ---------------
    qs = SearchQueryAggregate.objects.filter(
        index_name=index_name,
        date__gte=window_start,
    )
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)

    rows = qs.values("query").annotate(
        total=Sum("total_count"),
        zero=Sum("zero_result_count"),
    )

    # --- Trend: last-7 vs previous-7 per query -----------------------------
    recent_start = now - timedelta(days=7)
    previous_start = now - timedelta(days=14)

    recent_qs = SearchQueryAggregate.objects.filter(
        index_name=index_name,
        date__gte=recent_start,
    )
    previous_qs = SearchQueryAggregate.objects.filter(
        index_name=index_name,
        date__gte=previous_start,
        date__lt=recent_start,
    )
    if tenant_id:
        recent_qs = recent_qs.filter(tenant_id=tenant_id)
        previous_qs = previous_qs.filter(tenant_id=tenant_id)

    recent_map: dict[str, int] = {
        row["query"]: row["recent"] for row in recent_qs.values("query").annotate(recent=Sum("total_count"))
    }
    previous_map: dict[str, int] = {
        row["query"]: row["prev"] for row in previous_qs.values("query").annotate(prev=Sum("total_count"))
    }

    # --- CTR per query from SearchClickAggregate ---------------------------
    click_qs = SearchClickAggregate.objects.filter(
        index_name=index_name,
        date__gte=window_start,
    )
    if tenant_id:
        click_qs = click_qs.filter(tenant_id=tenant_id)

    # Total clicks per query across all documents.
    click_map: dict[str, int] = {
        row["query"]: row["clicks"] for row in click_qs.values("query").annotate(clicks=Sum("click_count"))
    }

    # --- Compile results ---------------------------------------------------
    compiled_patterns = []
    if exclude_patterns:
        for pattern in exclude_patterns:
            try:
                compiled_patterns.append(re.compile(pattern))
            except re.error:
                logger.warning("Invalid exclude_pattern regex: %r — skipped.", pattern)

    results: list[dict[str, Any]] = []

    for row in rows:
        query = row["query"]
        volume = row["total"] or 0
        zero = row["zero"] or 0

        if volume < min_volume:
            continue

        zero_result_rate = zero / volume if volume > 0 else 0.0
        gap_score = zero_result_rate * volume

        if gap_score < min_gap_score:
            continue

        if compiled_patterns and any(p.search(query) for p in compiled_patterns):
            continue

        recent = recent_map.get(query, 0)
        previous = previous_map.get(query, 0)
        trend = ((recent - previous) / previous * 100) if previous > 0 else 0.0

        total_clicks = click_map.get(query, 0)
        ctr = (total_clicks / volume) if volume > 0 and total_clicks else 0.0

        results.append(
            {
                "query": query,
                "volume": volume,
                "zero_result_rate": zero_result_rate,
                "gap_score": gap_score,
                "trend": trend,
                "ctr": ctr,
            }
        )

    results.sort(key=lambda r: r["gap_score"], reverse=True)
    return results


def cluster_queries(
    index_name: str,
    days: int = 30,
    similarity_threshold: float = 0.4,
    tenant_id: str = "",
) -> list[dict[str, Any]]:
    """Group queries by trigram similarity using PostgreSQL's ``pg_trgm`` extension.

    Requires the ``pg_trgm`` PostgreSQL extension to be installed. Raises
    ``ImproperlyConfigured`` if the extension is absent (BR-023).

    Args:
        index_name: Logical search index name to scope the query.
        days: Look-back window in days.
        similarity_threshold: Minimum trigram similarity (0.0–1.0) for two
            queries to belong to the same cluster. Lower values produce broader
            clusters.
        tenant_id: Restrict results to a specific tenant.

    Returns:
        List of cluster dicts ordered by ``total_volume`` descending, each
        with:

        - ``representative_query`` (str): Cluster member with the highest volume.
        - ``member_queries`` (list[str]): All other cluster members.
        - ``total_volume`` (int): Sum of volumes across all cluster members.
        - ``avg_zero_result_rate`` (float): Volume-weighted average zero-result
          rate across all cluster members.
    """
    from django.db import connection

    from icv_search.models.aggregates import SearchQueryAggregate

    _check_pg_trgm()

    now = timezone.now().date()
    window_start = now - timedelta(days=days)

    # Fetch per-query stats.
    qs = SearchQueryAggregate.objects.filter(
        index_name=index_name,
        date__gte=window_start,
    )
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)

    rows = list(
        qs.values("query").annotate(
            total=Sum("total_count"),
            zero=Sum("zero_result_count"),
        )
    )

    if not rows:
        return []

    # Build lookup: query -> (volume, zero_result_rate)
    stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        q = row["query"]
        volume = row["total"] or 0
        zero = row["zero"] or 0
        stats[q] = {
            "volume": volume,
            "zero_result_rate": (zero / volume) if volume > 0 else 0.0,
        }

    queries = list(stats.keys())

    if len(queries) < 2:
        # Nothing to cluster.
        if queries:
            q = queries[0]
            return [
                {
                    "representative_query": q,
                    "member_queries": [],
                    "total_volume": stats[q]["volume"],
                    "avg_zero_result_rate": stats[q]["zero_result_rate"],
                }
            ]
        return []

    # Use a raw SQL cross-join with pg_trgm similarity to find similar pairs.
    # Passing the table name and threshold as parameters safely.
    table_name = SearchQueryAggregate._meta.db_table

    sql = f"""
        SELECT a.query AS q1, b.query AS q2
        FROM (
            SELECT DISTINCT query
            FROM {table_name}
            WHERE index_name = %s
              AND date >= %s
              {("AND tenant_id = %s" if tenant_id else "")}
        ) a
        CROSS JOIN (
            SELECT DISTINCT query
            FROM {table_name}
            WHERE index_name = %s
              AND date >= %s
              {("AND tenant_id = %s" if tenant_id else "")}
        ) b
        WHERE a.query < b.query
          AND similarity(a.query, b.query) >= %s
    """

    if tenant_id:
        params = [
            index_name,
            window_start,
            tenant_id,
            index_name,
            window_start,
            tenant_id,
            similarity_threshold,
        ]
    else:
        params = [
            index_name,
            window_start,
            index_name,
            window_start,
            similarity_threshold,
        ]

    similar_pairs: list[tuple[str, str]] = []
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        similar_pairs = cursor.fetchall()

    # Build clusters via union-find.
    uf = _UnionFind()
    for q in queries:
        uf.find(q)  # ensure every query is registered
    for q1, q2 in similar_pairs:
        uf.union(q1, q2)

    # Group queries by their root.
    from collections import defaultdict

    groups: dict[str, list[str]] = defaultdict(list)
    for q in queries:
        root = uf.find(q)
        groups[root].append(q)

    # Build result dicts.
    results: list[dict[str, Any]] = []
    for members in groups.values():
        # Representative = member with highest volume.
        members.sort(key=lambda q: stats[q]["volume"], reverse=True)
        representative = members[0]
        others = members[1:]

        total_volume = sum(stats[m]["volume"] for m in members)

        # Volume-weighted avg zero-result rate.
        if total_volume > 0:
            avg_zero = sum(stats[m]["zero_result_rate"] * stats[m]["volume"] for m in members) / total_volume
        else:
            avg_zero = 0.0

        results.append(
            {
                "representative_query": representative,
                "member_queries": others,
                "total_volume": total_volume,
                "avg_zero_result_rate": avg_zero,
            }
        )

    results.sort(key=lambda r: r["total_volume"], reverse=True)
    return results


def suggest_synonyms(
    index_name: str,
    days: int = 30,
    confidence_threshold: float = 0.7,
    tenant_id: str = "",
) -> list[dict[str, Any]]:
    """Find zero-result queries that are trigram-similar to successful queries.

    Uses PostgreSQL's ``pg_trgm`` extension to compute pairwise similarity
    between zero-result queries and successful queries. Raises
    ``ImproperlyConfigured`` if the extension is absent (BR-023).

    Args:
        index_name: Logical search index name to scope the query.
        days: Look-back window in days.
        confidence_threshold: Minimum confidence to include a suggestion.
        tenant_id: Restrict results to a specific tenant.

    Returns:
        List of suggestion dicts ordered by ``confidence`` descending, each
        with:

        - ``source_query`` (str): The zero-result query.
        - ``suggested_synonym`` (str): The most similar successful query.
        - ``confidence`` (float): Trigram similarity weighted by evidence count.
        - ``evidence_count`` (int): Number of similar successful queries found.
    """
    from django.db import connection

    from icv_search.models.aggregates import SearchQueryAggregate

    _check_pg_trgm()

    now = timezone.now().date()
    window_start = now - timedelta(days=days)

    base_qs = SearchQueryAggregate.objects.filter(
        index_name=index_name,
        date__gte=window_start,
    )
    if tenant_id:
        base_qs = base_qs.filter(tenant_id=tenant_id)

    # Aggregate per query over the window.
    agg_rows = list(
        base_qs.values("query").annotate(
            total=Sum("total_count"),
            zero=Sum("zero_result_count"),
        )
    )

    if not agg_rows:
        return []

    # Split into zero-result queries and successful queries.
    zero_result_queries: list[str] = []
    successful_queries: list[str] = []

    for row in agg_rows:
        volume = row["total"] or 0
        zero = row["zero"] or 0
        if volume == 0:
            continue
        rate = zero / volume
        if rate > 0.5:
            zero_result_queries.append(row["query"])
        elif rate < 0.2:
            successful_queries.append(row["query"])

    if not zero_result_queries or not successful_queries:
        return []

    # Use pg_trgm to find similar (zero_result_query, successful_query) pairs.
    table_name = SearchQueryAggregate._meta.db_table
    tenant_filter = "AND tenant_id = %s" if tenant_id else ""

    sql = f"""
        SELECT
            z.query  AS source_query,
            s.query  AS successful_query,
            similarity(z.query, s.query) AS sim
        FROM (
            SELECT DISTINCT query
            FROM {table_name}
            WHERE index_name = %s
              AND date >= %s
              {tenant_filter}
        ) z
        CROSS JOIN (
            SELECT DISTINCT query
            FROM {table_name}
            WHERE index_name = %s
              AND date >= %s
              {tenant_filter}
        ) s
        WHERE z.query = ANY(%s)
          AND s.query = ANY(%s)
          AND z.query <> s.query
          AND similarity(z.query, s.query) > 0
        ORDER BY z.query, sim DESC
    """

    if tenant_id:
        params: list[Any] = [
            index_name,
            window_start,
            tenant_id,
            index_name,
            window_start,
            tenant_id,
            zero_result_queries,
            successful_queries,
        ]
    else:
        params = [
            index_name,
            window_start,
            index_name,
            window_start,
            zero_result_queries,
            successful_queries,
        ]

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        pair_rows = cursor.fetchall()

    # For each source query, collect best match + evidence count.
    from collections import defaultdict

    # pairs_by_source: source -> list of (successful_query, sim)
    pairs_by_source: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for source_query, successful_query, sim in pair_rows:
        pairs_by_source[source_query].append((successful_query, float(sim)))

    results: list[dict[str, Any]] = []

    for source_query, candidates in pairs_by_source.items():
        # Sort by similarity descending.
        candidates.sort(key=lambda c: c[1], reverse=True)
        best_synonym, best_sim = candidates[0]
        evidence_count = len(candidates)

        # Confidence = similarity weighted by evidence (capped at 1.0).
        # More corroborating matches increase confidence slightly.
        evidence_factor = min(1.0, 1.0 + (evidence_count - 1) * 0.02)
        confidence = min(1.0, best_sim * evidence_factor)

        if confidence < confidence_threshold:
            continue

        results.append(
            {
                "source_query": source_query,
                "suggested_synonym": best_synonym,
                "confidence": confidence,
                "evidence_count": evidence_count,
            }
        )

    results.sort(key=lambda r: r["confidence"], reverse=True)
    return results


def auto_create_rewrites(
    index_name: str,
    confidence_threshold: float | None = None,
    tenant_id: str = "",
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Create ``SearchRewrite`` rules from high-confidence synonym suggestions.

    Calls :func:`suggest_synonyms` and creates ``SearchRewrite`` records for
    suggestions that meet ``confidence_threshold`` (BR-022). Suggestions below
    the threshold are returned with ``action: "skipped"`` but are never written
    to the database.

    Requires ``ICV_SEARCH_MERCHANDISING_ENABLED = True``. Raises
    ``ImproperlyConfigured`` if merchandising is disabled.

    Args:
        index_name: Logical search index name to scope the query.
        confidence_threshold: Minimum confidence to create a rewrite. When
            ``None``, reads from ``ICV_SEARCH_AUTO_SYNONYM_CONFIDENCE``
            (default 0.8).
        tenant_id: Restrict results to a specific tenant.
        dry_run: When ``True``, no ``SearchRewrite`` records are created;
            the function returns what would have been created.

    Returns:
        List of result dicts, one per suggestion, each with:

        - ``source_query`` (str): The zero-result (source) query.
        - ``suggested_synonym`` (str): The proposed synonym.
        - ``confidence`` (float): Confidence score from ``suggest_synonyms``.
        - ``action`` (str): ``"created"``, ``"already_exists"``, or
          ``"skipped"``.
        - ``rewrite_id`` (str | None): UUID of the created/existing
          ``SearchRewrite``, or ``None`` when action is ``"skipped"``.
    """
    if confidence_threshold is None:
        confidence_threshold = _get_auto_synonym_confidence()

    if not _get_merchandising_enabled():
        raise ImproperlyConfigured(
            "auto_create_rewrites() requires ICV_SEARCH_MERCHANDISING_ENABLED = True. "
            "SearchRewrite is a merchandising model — enable merchandising before "
            "calling this function."
        )

    from icv_search.models.merchandising import QueryRewrite

    # Fetch all suggestions (no pre-filtering by threshold — we need to mark
    # below-threshold entries as "skipped" in the return value).
    suggestions = suggest_synonyms(
        index_name=index_name,
        tenant_id=tenant_id,
        confidence_threshold=0.0,
    )

    results: list[dict[str, Any]] = []

    for suggestion in suggestions:
        source_query = suggestion["source_query"]
        suggested_synonym = suggestion["suggested_synonym"]
        confidence = suggestion["confidence"]

        if confidence < confidence_threshold:
            results.append(
                {
                    "source_query": source_query,
                    "suggested_synonym": suggested_synonym,
                    "confidence": confidence,
                    "action": "skipped",
                    "rewrite_id": None,
                }
            )
            continue

        # Check for an existing rewrite for this query pattern on this index.
        existing = QueryRewrite.objects.filter(
            index_name=index_name,
            query_pattern=source_query,
            match_type="exact",
            tenant_id=tenant_id,
        ).first()

        if existing:
            results.append(
                {
                    "source_query": source_query,
                    "suggested_synonym": suggested_synonym,
                    "confidence": confidence,
                    "action": "already_exists",
                    "rewrite_id": str(existing.pk),
                }
            )
            continue

        if dry_run:
            results.append(
                {
                    "source_query": source_query,
                    "suggested_synonym": suggested_synonym,
                    "confidence": confidence,
                    "action": "created",
                    "rewrite_id": None,
                }
            )
            continue

        rewrite = QueryRewrite.objects.create(
            index_name=index_name,
            query_pattern=source_query,
            match_type="exact",
            rewritten_query=suggested_synonym,
            tenant_id=tenant_id,
        )
        logger.info(
            "Created SearchRewrite for %r -> %r on index %r (confidence %.2f).",
            source_query,
            suggested_synonym,
            index_name,
            confidence,
        )
        results.append(
            {
                "source_query": source_query,
                "suggested_synonym": suggested_synonym,
                "confidence": confidence,
                "action": "created",
                "rewrite_id": str(rewrite.pk),
            }
        )

    return results
