"""Fluent query builder DSL for icv-search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from icv_search.models import SearchIndex
    from icv_search.pagination import ICVSearchPaginator
    from icv_search.types import SearchResult


class SearchQuery:
    """Fluent query builder for icv-search.

    Provides a chainable interface for constructing and executing search
    queries.  Each method returns ``self`` so calls can be chained.

    Example::

        from icv_search.query import SearchQuery

        results = (
            SearchQuery("products")
            .text("running shoes")
            .filter(brand="Nike", price__gte=50)
            .sort("-price", "name")
            .facets("brand", "category")
            .highlight("name", "description")
            .geo_near(lat=51.5, lng=-0.12, radius=5000)
            .limit(20)
            .offset(0)
            .execute()
        )
    """

    def __init__(self, index: str | SearchIndex) -> None:
        """Initialise the query builder.

        Args:
            index: Logical index name string or a
                :class:`~icv_search.models.SearchIndex` instance.
        """
        self._index = index
        self._query: str = ""
        self._filters: dict[str, Any] = {}
        self._sort: list[str] = []
        self._facets: list[str] = []
        self._highlight: dict[str, Any] = {}
        self._crop: dict[str, Any] = {}
        self._geo: dict[str, Any] = {}
        self._geo_bbox: tuple | None = None
        self._geo_polygon: list | None = None
        self._limit: int | None = None
        self._offset: int | None = None
        self._page: int | None = None
        self._hits_per_page: int | None = None
        self._with_ranking_scores: bool = False
        self._with_ranking_score_details: bool = False
        self._with_matches_position: bool = False
        self._matching_strategy: str | None = None
        self._attributes_to_retrieve: list[str] | None = None
        self._attributes_to_search_on: list[str] | None = None
        self._ranking_score_threshold: float | None = None
        self._distinct: str | None = None
        self._hybrid: dict[str, Any] | None = None
        self._vector: list[float] | None = None
        self._retrieve_vectors: bool = False
        self._locales: list[str] | None = None
        self._tenant: str = ""
        self._user: Any = None
        self._metadata: dict[str, Any] = {}

    # ------------------------------------------------------------------ text

    def text(self, query: str) -> SearchQuery:
        """Set the full-text query string.

        Args:
            query: The search terms submitted by the user.

        Returns:
            ``self`` for chaining.
        """
        self._query = query
        return self

    # --------------------------------------------------------------- filters

    def filter(self, **kwargs: Any) -> SearchQuery:
        """Add filter conditions.

        Multiple calls are merged; later calls override duplicate keys.

        Supports simple equality values and Django-style lookup suffixes::

            .filter(brand="Nike")           # equality
            .filter(price__gte=50)          # greater-than-or-equal
            .filter(category__in=["shoes"]) # membership

        Lookup suffixes are translated to the engine filter expression format
        when the query is executed.

        Args:
            **kwargs: Field lookups to filter by.

        Returns:
            ``self`` for chaining.
        """
        self._filters.update(kwargs)
        return self

    # ------------------------------------------------------------------ sort

    def sort(self, *fields: str) -> SearchQuery:
        """Set sort fields.

        Prefix a field name with ``-`` for descending order::

            .sort("-price", "name")

        Args:
            *fields: Field names to sort by, in priority order.

        Returns:
            ``self`` for chaining.
        """
        self._sort = list(fields)
        return self

    # ---------------------------------------------------------------- facets

    def facets(self, *fields: str) -> SearchQuery:
        """Request facet distribution for the given fields.

        Args:
            *fields: Field names to facet on.

        Returns:
            ``self`` for chaining.
        """
        self._facets = list(fields)
        return self

    # ------------------------------------------------------------- highlight

    def highlight(
        self,
        *fields: str,
        pre_tag: str | None = None,
        post_tag: str | None = None,
    ) -> SearchQuery:
        """Configure result highlighting.

        Args:
            *fields: Attribute names to highlight within.
            pre_tag: HTML tag inserted before a match (e.g. ``"<em>"``).
                Defaults to the engine default when ``None``.
            post_tag: HTML tag inserted after a match (e.g. ``"</em>"``).
                Defaults to the engine default when ``None``.

        Returns:
            ``self`` for chaining.
        """
        self._highlight = {"fields": list(fields)}
        if pre_tag is not None:
            self._highlight["pre_tag"] = pre_tag
        if post_tag is not None:
            self._highlight["post_tag"] = post_tag
        return self

    # ----------------------------------------------------------------- crop

    def crop(
        self,
        *fields: str,
        length: int | None = None,
        marker: str | None = None,
    ) -> SearchQuery:
        """Configure result cropping/snippets.

        Cropped excerpts appear in ``formatted_hits``.

        Args:
            *fields: Attribute names to crop.
            length: Words per cropped excerpt.
            marker: Boundary marker (e.g. ``"..."``).

        Returns:
            ``self`` for chaining.
        """
        self._crop = {"fields": list(fields)}
        if length is not None:
            self._crop["length"] = length
        if marker is not None:
            self._crop["marker"] = marker
        return self

    # ------------------------------------------------ attributes_to_retrieve

    def attributes_to_retrieve(self, *fields: str) -> SearchQuery:
        """Restrict which fields are returned in search results.

        Args:
            *fields: Field names to include.

        Returns:
            ``self`` for chaining.
        """
        self._attributes_to_retrieve = list(fields)
        return self

    # ----------------------------------------------- attributes_to_search_on

    def attributes_to_search_on(self, *fields: str) -> SearchQuery:
        """Restrict which fields are searched at query time.

        Args:
            *fields: Searchable field names to limit the query to.

        Returns:
            ``self`` for chaining.
        """
        self._attributes_to_search_on = list(fields)
        return self

    # ----------------------------------------------------------- distinct

    def distinct(self, field: str) -> SearchQuery:
        """Set query-time deduplication field.

        Only one document per distinct field value appears in results.

        Args:
            field: Field name to deduplicate on.

        Returns:
            ``self`` for chaining.
        """
        self._distinct = field
        return self

    # ------------------------------------------------------------ hybrid

    def hybrid(
        self,
        semantic_ratio: float = 0.5,
        embedder: str = "default",
    ) -> SearchQuery:
        """Enable hybrid (keyword + semantic) search.

        Args:
            semantic_ratio: Balance between keyword (0.0) and semantic (1.0).
            embedder: Name of the configured embedder to use.

        Returns:
            ``self`` for chaining.
        """
        self._hybrid = {"semanticRatio": semantic_ratio, "embedder": embedder}
        return self

    # ------------------------------------------------------------ vector

    def vector(self, embedding: list[float]) -> SearchQuery:
        """Pass a raw vector as the query (pure semantic search).

        Args:
            embedding: Float array matching the embedder dimensions.

        Returns:
            ``self`` for chaining.
        """
        self._vector = embedding
        return self

    # ------------------------------------------------------- retrieve_vectors

    def retrieve_vectors(self) -> SearchQuery:
        """Include ``_vectors`` in each hit of the response.

        Returns:
            ``self`` for chaining.
        """
        self._retrieve_vectors = True
        return self

    # ------------------------------------------- ranking_score_threshold

    def ranking_score_threshold(self, threshold: float) -> SearchQuery:
        """Exclude results below this relevance score (0–1).

        Args:
            threshold: Minimum ranking score.

        Returns:
            ``self`` for chaining.
        """
        self._ranking_score_threshold = threshold
        return self

    # ------------------------------------------- show_matches_position

    def show_matches_position(self) -> SearchQuery:
        """Request byte-level offsets of matched terms in each hit.

        Returns:
            ``self`` for chaining.
        """
        self._with_matches_position = True
        return self

    # ---------------------------------------- show_ranking_score_details

    def show_ranking_score_details(self) -> SearchQuery:
        """Request per-rule ranking score breakdown for each hit.

        Returns:
            ``self`` for chaining.
        """
        self._with_ranking_score_details = True
        return self

    # ----------------------------------------------------------- locales

    def locales(self, *codes: str) -> SearchQuery:
        """Set ISO-639 language codes for the query.

        Args:
            *codes: Language codes (e.g. ``"eng"``, ``"jpn"``).

        Returns:
            ``self`` for chaining.
        """
        self._locales = list(codes)
        return self

    # ------------------------------------------------------------- page

    def page(self, number: int, per_page: int = 20) -> SearchQuery:
        """Use page-based pagination instead of offset-based.

        Args:
            number: Page number (1-indexed).
            per_page: Results per page.

        Returns:
            ``self`` for chaining.
        """
        self._page = number
        self._hits_per_page = per_page
        return self

    # --------------------------------------------------------------- geo_near

    def geo_near(
        self,
        lat: float,
        lng: float,
        radius: int | None = None,
        sort: str = "asc",
    ) -> SearchQuery:
        """Filter and/or sort results by proximity to a geographic point.

        Args:
            lat: Latitude of the centre point.
            lng: Longitude of the centre point.
            radius: Maximum distance in metres.  ``None`` means no radius
                filter — results are sorted by distance only.
            sort: Sort direction — ``"asc"`` (nearest first) or
                ``"desc"`` (furthest first).

        Returns:
            ``self`` for chaining.
        """
        self._geo = {"lat": lat, "lng": lng, "sort": sort}
        if radius is not None:
            self._geo["radius"] = radius
        return self

    # ------------------------------------------------------------ geo_bbox

    def geo_bbox(
        self,
        top_right: tuple[float, float],
        bottom_left: tuple[float, float],
    ) -> SearchQuery:
        """Filter results within a geographic bounding box.

        Args:
            top_right: ``(lat, lng)`` of the top-right corner.
            bottom_left: ``(lat, lng)`` of the bottom-left corner.

        Returns:
            ``self`` for chaining.
        """
        self._geo_bbox = (top_right, bottom_left)
        return self

    # --------------------------------------------------------- geo_polygon

    def geo_polygon(self, vertices: list[tuple[float, float]]) -> SearchQuery:
        """Filter results within a geographic polygon.

        Args:
            vertices: List of ``(lat, lng)`` vertices defining the polygon.

        Returns:
            ``self`` for chaining.
        """
        self._geo_polygon = vertices
        return self

    # --------------------------------------------------------------- paging

    def limit(self, n: int) -> SearchQuery:
        """Set the maximum number of results to return.

        Args:
            n: Page size.

        Returns:
            ``self`` for chaining.
        """
        self._limit = n
        return self

    def offset(self, n: int) -> SearchQuery:
        """Set the number of results to skip (zero-based).

        Args:
            n: Offset from the first result.

        Returns:
            ``self`` for chaining.
        """
        self._offset = n
        return self

    # -------------------------------------------------------- ranking scores

    def with_ranking_scores(self) -> SearchQuery:
        """Request per-hit ranking scores from the engine.

        Returns:
            ``self`` for chaining.
        """
        self._with_ranking_scores = True
        return self

    # -------------------------------------------------- matching strategy

    def matching_strategy(self, strategy: str) -> SearchQuery:
        """Set the token matching strategy.

        Common values (Meilisearch): ``"last"`` (default), ``"all"``,
        ``"frequency"``.

        Args:
            strategy: Strategy name supported by the configured backend.

        Returns:
            ``self`` for chaining.
        """
        self._matching_strategy = strategy
        return self

    # --------------------------------------------------------------- tenant

    def tenant(self, tenant_id: str) -> SearchQuery:
        """Set the tenant identifier for multi-tenant index resolution.

        Args:
            tenant_id: Tenant identifier string.

        Returns:
            ``self`` for chaining.
        """
        self._tenant = tenant_id
        return self

    # --------------------------------------------------------------- analytics

    def user(self, user: Any) -> SearchQuery:
        """Attach the requesting user for analytics logging.

        Args:
            user: Django user model instance (or ``None``).

        Returns:
            ``self`` for chaining.
        """
        self._user = user
        return self

    def metadata(self, data: dict[str, Any]) -> SearchQuery:
        """Attach arbitrary metadata for analytics logging.

        The dict is stored verbatim on the
        :class:`~icv_search.models.analytics.SearchQueryLog` record.

        Args:
            data: Arbitrary key/value context (e.g. ``{"page": "homepage"}``).

        Returns:
            ``self`` for chaining.
        """
        self._metadata = data
        return self

    # --------------------------------------------------------------- execute

    def _build_params(self) -> dict[str, Any]:
        """Compile the accumulated state into a params dict for :func:`search`."""
        params: dict[str, Any] = {}

        if self._filters:
            params["filter"] = _build_filter_expression(self._filters)

        if self._sort:
            params["sort"] = list(self._sort)

        if self._facets:
            params["facets"] = list(self._facets)

        if self._highlight:
            params["highlight_fields"] = self._highlight["fields"]
            if "pre_tag" in self._highlight:
                params["highlight_pre_tag"] = self._highlight["pre_tag"]
            if "post_tag" in self._highlight:
                params["highlight_post_tag"] = self._highlight["post_tag"]

        if self._crop:
            params["crop_fields"] = self._crop["fields"]
            if "length" in self._crop:
                params["crop_length"] = self._crop["length"]
            if "marker" in self._crop:
                params["crop_marker"] = self._crop["marker"]

        if self._geo:
            params["geo_point"] = (self._geo["lat"], self._geo["lng"])
            if "radius" in self._geo:
                params["geo_radius"] = self._geo["radius"]
            if self._geo.get("sort"):
                params["geo_sort"] = self._geo["sort"]

        if self._geo_bbox is not None:
            params["geo_bbox"] = self._geo_bbox

        if self._geo_polygon is not None:
            params["geo_polygon"] = self._geo_polygon

        if self._limit is not None:
            params["limit"] = self._limit

        if self._offset is not None:
            params["offset"] = self._offset

        if self._page is not None:
            params["page"] = self._page

        if self._hits_per_page is not None:
            params["hits_per_page"] = self._hits_per_page

        if self._with_ranking_scores:
            params["show_ranking_score"] = True

        if self._with_ranking_score_details:
            params["show_ranking_score_details"] = True

        if self._with_matches_position:
            params["show_matches_position"] = True

        if self._matching_strategy is not None:
            params["matching_strategy"] = self._matching_strategy

        if self._attributes_to_retrieve is not None:
            params["attributes_to_retrieve"] = self._attributes_to_retrieve

        if self._attributes_to_search_on is not None:
            params["attributes_to_search_on"] = self._attributes_to_search_on

        if self._ranking_score_threshold is not None:
            params["ranking_score_threshold"] = self._ranking_score_threshold

        if self._distinct is not None:
            params["distinct"] = self._distinct

        if self._hybrid is not None:
            params["hybrid"] = self._hybrid

        if self._vector is not None:
            params["vector"] = self._vector

        if self._retrieve_vectors:
            params["retrieve_vectors"] = True

        if self._locales is not None:
            params["locales"] = self._locales

        return params

    def execute(self) -> SearchResult:
        """Execute the query and return a :class:`~icv_search.types.SearchResult`.

        The :func:`~icv_search.services.search` service function is called
        with all accumulated parameters.  If query logging is enabled the
        result is recorded automatically.

        Returns:
            Normalised :class:`~icv_search.types.SearchResult` instance.
        """
        from icv_search.services.search import search

        params = self._build_params()

        return search(
            self._index,
            self._query,
            tenant_id=self._tenant,
            user=self._user,
            metadata=self._metadata,
            **params,
        )

    def paginate(self, per_page: int = 20) -> ICVSearchPaginator:
        """Execute the query and wrap the result in an
        :class:`~icv_search.pagination.ICVSearchPaginator`.

        Sets ``limit`` to ``per_page`` before executing so the engine returns
        the correct page slice.

        Args:
            per_page: Number of results per page.

        Returns:
            :class:`~icv_search.pagination.ICVSearchPaginator` wrapping the
            search result.
        """
        from icv_search.pagination import ICVSearchPaginator

        self._limit = per_page
        result = self.execute()
        return ICVSearchPaginator(result, per_page=per_page)


# ------------------------------------------------------------------ helpers


def _build_filter_expression(filters: dict[str, Any]) -> list[str]:
    """Convert a kwargs-style filter dict to a list of engine filter strings.

    Supports plain equality and Django-style lookup suffixes:

    - ``field="value"`` → ``'field = "value"'``
    - ``field__gte=50`` → ``"field >= 50"``
    - ``field__lte=50`` → ``"field <= 50"``
    - ``field__gt=50`` → ``"field > 50"``
    - ``field__lt=50`` → ``"field < 50"``
    - ``field__in=["a","b"]`` → ``'field IN ["a", "b"]'``
    - ``field__ne="x"`` → ``'field != "x"'``

    Args:
        filters: Dict of field lookups.

    Returns:
        List of filter expression strings suitable for passing to the engine.
    """
    _OPERATOR_MAP = {
        "gte": ">=",
        "lte": "<=",
        "gt": ">",
        "lt": "<",
        "ne": "!=",
    }

    expressions: list[str] = []

    for key, value in filters.items():
        parts = key.rsplit("__", 1)
        if len(parts) == 2 and parts[1] in _OPERATOR_MAP:
            field, lookup = parts
            op = _OPERATOR_MAP[lookup]
            expressions.append(f"{field} {op} {_format_value(value)}")
        elif len(parts) == 2 and parts[1] == "in":
            field = parts[0]
            formatted = "[" + ", ".join(_format_value(v) for v in value) + "]"
            expressions.append(f"{field} IN {formatted}")
        else:
            expressions.append(f"{key} = {_format_value(value)}")

    return expressions


def _format_value(value: Any) -> str:
    """Format a Python value as an engine filter token."""
    if isinstance(value, str):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
