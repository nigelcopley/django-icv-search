"""Normalised response types for the icv-search abstraction layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskResult:
    """Result of an asynchronous engine operation (index creation, document add, etc.)."""

    task_uid: str = ""
    status: str = ""
    detail: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_engine(cls, data: dict[str, Any]) -> TaskResult:
        """Create from a raw engine response dict.

        Accepts the task UID under any of the following keys (in priority order):
        ``taskUid`` (Meilisearch async operations), ``task_uid``, or ``uid``
        (task-status responses from Postgres and DummyBackend ``get_task``).
        """
        task_uid = str(data.get("taskUid", data.get("task_uid", data.get("uid", ""))))
        return cls(
            task_uid=task_uid,
            status=str(data.get("status", "")),
            detail=str(data.get("type", "")),
            raw=data,
        )


@dataclass
class SearchResult:
    """Result of a search query."""

    hits: list[dict[str, Any]] = field(default_factory=list)
    query: str = ""
    processing_time_ms: int = 0
    estimated_total_hits: int = 0
    limit: int = 20
    offset: int = 0
    facet_distribution: dict[str, dict[str, int]] = field(default_factory=dict)
    formatted_hits: list[dict[str, Any]] = field(default_factory=list)
    ranking_scores: list[float | None] = field(default_factory=list)
    ranking_score_details: list[dict[str, Any] | None] = field(default_factory=list)
    matches_position: list[dict[str, Any] | None] = field(default_factory=list)
    page: int | None = None
    hits_per_page: int | None = None
    total_hits: int | None = None
    total_pages: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    # Internal keys stripped from plain hits.
    _INTERNAL_HIT_KEYS = frozenset({
        "_formatted", "_rankingScore", "_rankingScoreDetails",
        "_matchesPosition", "_vectors",
    })

    @classmethod
    def from_engine(cls, data: dict[str, Any]) -> SearchResult:
        """Create from a raw engine response dict.

        Extracts ``_formatted`` from each Meilisearch hit (populated when
        ``attributesToHighlight`` or ``attributesToCrop`` is requested) and
        stores the results in ``formatted_hits``. For other backends, a
        top-level ``formatted_hits`` key is accepted directly.

        Ranking scores are extracted from:

        - ``_rankingScore`` on each hit (Meilisearch v1.3+ when
          ``showRankingScore: true`` is passed to the search request).
        - A top-level ``ranking_scores`` list (Postgres and Dummy backends).

        When neither source is present the list is empty.

        Ranking score details are extracted from ``_rankingScoreDetails`` on
        each hit (when ``showRankingScoreDetails: true`` is passed).

        Match positions are extracted from ``_matchesPosition`` on each hit
        (when ``showMatchesPosition: true`` is passed).

        Page-based pagination fields (``page``, ``hitsPerPage``,
        ``totalHits``, ``totalPages``) are populated when the response uses
        page-based pagination instead of offset-based.
        """
        raw_hits: list[dict[str, Any]] = data.get("hits", [])

        # Meilisearch embeds highlighted/cropped versions as a ``_formatted``
        # key on each hit.  Extract those into a parallel list.
        meili_formatted = [hit["_formatted"] for hit in raw_hits if "_formatted" in hit]

        # Backends that build highlighted hits server-side (Postgres, Dummy)
        # return them under a top-level ``formatted_hits`` key.
        formatted_hits: list[dict[str, Any]] = meili_formatted or data.get("formatted_hits", [])

        # Extract ranking scores.  Meilisearch embeds ``_rankingScore`` on each
        # hit; other backends may supply a top-level list.
        meili_scores: list[float | None] = [hit.get("_rankingScore") for hit in raw_hits if "_rankingScore" in hit]
        ranking_scores: list[float | None] = meili_scores if meili_scores else data.get("ranking_scores", [])

        # Extract ranking score details (per-rule breakdown).
        ranking_score_details: list[dict[str, Any] | None] = [
            hit.get("_rankingScoreDetails") for hit in raw_hits
            if "_rankingScoreDetails" in hit
        ]

        # Extract match positions.
        matches_position: list[dict[str, Any] | None] = [
            hit.get("_matchesPosition") for hit in raw_hits
            if "_matchesPosition" in hit
        ]

        # Strip internal Meilisearch keys from the plain hits to keep them clean.
        # ``_geoDistance`` is intentionally preserved — Meilisearch adds this
        # automatically when geo search is used and it is useful to callers.
        clean_hits = [{k: v for k, v in hit.items() if k not in cls._INTERNAL_HIT_KEYS} for hit in raw_hits]

        # Determine total hits — page-based responses use ``totalHits``,
        # offset-based use ``estimatedTotalHits``.
        estimated = int(data.get("estimatedTotalHits", data.get("estimated_total_hits", 0)))
        total_hits_val = data.get("totalHits")
        if total_hits_val is not None:
            estimated = int(total_hits_val)

        return cls(
            hits=clean_hits,
            query=str(data.get("query", "")),
            processing_time_ms=int(data.get("processingTimeMs", data.get("processing_time_ms", 0))),
            estimated_total_hits=estimated,
            limit=int(data.get("limit", 20)),
            offset=int(data.get("offset", 0)),
            facet_distribution=data.get("facetDistribution", data.get("facet_distribution", {})),
            formatted_hits=formatted_hits,
            ranking_scores=ranking_scores,
            ranking_score_details=ranking_score_details,
            matches_position=matches_position,
            page=data.get("page"),
            hits_per_page=data.get("hitsPerPage"),
            total_hits=int(total_hits_val) if total_hits_val is not None else None,
            total_pages=data.get("totalPages"),
            raw=data,
        )

    def get_highlighted_hits(self) -> list[dict[str, Any]]:
        """Return highlighted hits when available, falling back to plain hits.

        Use this in templates and views instead of accessing ``hits`` directly
        when highlighting may have been requested — the method transparently
        returns whichever version is populated.
        """
        return self.formatted_hits if self.formatted_hits else self.hits

    def get_hit_with_score(self, index: int) -> tuple[dict[str, Any], float | None]:
        """Return the hit at ``index`` paired with its ranking score (or ``None``).

        Example::

            result = search("products", "chair")
            hit, score = result.get_hit_with_score(0)
            print(hit["name"], score)  # "Office Chair", 0.9872

        Args:
            index: Zero-based position in the ``hits`` list.

        Returns:
            A ``(hit, score)`` tuple.  ``score`` is ``None`` when ranking
            scores were not requested or are not available for that hit.
        """
        hit = self.hits[index]
        score: float | None = self.ranking_scores[index] if index < len(self.ranking_scores) else None
        return hit, score

    def get_facet_values(self, facet_name: str) -> list[dict[str, Any]]:
        """Return facet values sorted by count descending.

        Returns a list of dicts with 'name' and 'count' keys, e.g.::

            [{'name': 'Nike', 'count': 42}, {'name': 'Adidas', 'count': 31}]
        """
        distribution = self.facet_distribution.get(facet_name, {})
        return sorted(
            [{"name": name, "count": count} for name, count in distribution.items()],
            key=lambda x: x["count"],
            reverse=True,
        )


@dataclass
class MerchandisedSearchResult:
    """Extended search result carrying merchandising metadata.

    Wraps all fields of :class:`SearchResult` plus merchandising-specific
    annotations: redirect instructions, banners, applied rules, rewrite
    tracking, and fallback flags.
    """

    hits: list[dict[str, Any]] = field(default_factory=list)
    query: str = ""
    processing_time_ms: int = 0
    estimated_total_hits: int = 0
    limit: int = 20
    offset: int = 0
    facet_distribution: dict[str, dict[str, int]] = field(default_factory=dict)
    formatted_hits: list[dict[str, Any]] = field(default_factory=list)
    ranking_scores: list[float | None] = field(default_factory=list)
    ranking_score_details: list[dict[str, Any] | None] = field(default_factory=list)
    matches_position: list[dict[str, Any] | None] = field(default_factory=list)
    page: int | None = None
    hits_per_page: int | None = None
    total_hits: int | None = None
    total_pages: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    # Merchandising-specific fields
    redirect: Any | None = None
    banners: list = field(default_factory=list)
    applied_rules: list[dict[str, Any]] = field(default_factory=list)
    original_query: str = ""
    was_rewritten: bool = False
    is_fallback: bool = False

    # Intelligence fields (v0.6.0)
    preprocessed: Any | None = None  # PreprocessedQuery when preprocessor is configured
    detected_intent: str = ""

    @classmethod
    def from_search_result(cls, result: SearchResult, **kwargs: Any) -> MerchandisedSearchResult:
        """Create from an existing :class:`SearchResult`, carrying over all fields."""
        return cls(
            hits=result.hits,
            query=result.query,
            processing_time_ms=result.processing_time_ms,
            estimated_total_hits=result.estimated_total_hits,
            limit=result.limit,
            offset=result.offset,
            facet_distribution=result.facet_distribution,
            formatted_hits=result.formatted_hits,
            ranking_scores=result.ranking_scores,
            ranking_score_details=result.ranking_score_details,
            matches_position=result.matches_position,
            page=result.page,
            hits_per_page=result.hits_per_page,
            total_hits=result.total_hits,
            total_pages=result.total_pages,
            raw=result.raw,
            **kwargs,
        )

    def get_highlighted_hits(self) -> list[dict[str, Any]]:
        """Return highlighted hits when available, falling back to plain hits."""
        return self.formatted_hits if self.formatted_hits else self.hits

    def get_hit_with_score(self, index: int) -> tuple[dict[str, Any], float | None]:
        """Return the hit at ``index`` paired with its ranking score (or ``None``)."""
        hit = self.hits[index]
        score: float | None = self.ranking_scores[index] if index < len(self.ranking_scores) else None
        return hit, score

    def get_facet_values(self, facet_name: str) -> list[dict[str, Any]]:
        """Return facet values sorted by count descending."""
        distribution = self.facet_distribution.get(facet_name, {})
        return sorted(
            [{"name": name, "count": count} for name, count in distribution.items()],
            key=lambda x: x["count"],
            reverse=True,
        )


@dataclass
class QueryContext:
    """Context passed to the query preprocessor callable.

    Provides enough information for the preprocessor to make decisions about
    query transformation, filter extraction, and intent classification.
    """

    index_name: str = ""
    tenant_id: str = ""
    original_query: str = ""
    user: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreprocessedQuery:
    """Result returned by the query preprocessor callable.

    Controls how the search pipeline handles the transformed query, including
    extracted filters, sort order, detected intent, and short-circuit options.
    """

    query: str = ""
    extracted_filters: dict[str, Any] = field(default_factory=dict)
    extracted_sort: list[str] = field(default_factory=list)
    intent: str = ""
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    skip_search: bool = False
    redirect_url: str = ""


@dataclass
class IndexStats:
    """Statistics for a search index."""

    document_count: int = 0
    is_indexing: bool = False
    field_distribution: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_engine(cls, data: dict[str, Any]) -> IndexStats:
        """Create from a raw engine response dict."""
        return cls(
            document_count=int(data.get("numberOfDocuments", data.get("document_count", 0))),
            is_indexing=bool(data.get("isIndexing", data.get("is_indexing", False))),
            field_distribution=data.get("fieldDistribution", data.get("field_distribution", {})),
            raw=data,
        )
