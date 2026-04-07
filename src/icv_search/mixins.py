"""SearchableMixin for Django models."""

from __future__ import annotations

from typing import Any


class SearchableMixin:
    """Mixin for Django models that should be indexed in a search engine.

    Declare indexing configuration on your model class, then use the
    icv_search service functions to index instances.

    Example::

        class Product(SearchableMixin, BaseModel):
            search_index_name = "products"
            search_fields = ["name", "description", "sku"]
            search_filterable_fields = ["category", "is_active"]
            search_sortable_fields = ["price", "created_at"]

            name = models.CharField(max_length=200)
            description = models.TextField()
            sku = models.CharField(max_length=50)
            category = models.CharField(max_length=100)
            price = models.DecimalField(max_digits=10, decimal_places=2)

    Geo search
    ----------
    Set ``search_geo_field`` to the name of a model property or attribute that
    returns a ``(lat, lng)`` tuple, or set separate ``search_lat_field`` and
    ``search_lng_field`` attribute names.  When ``search_geo_field`` is set,
    ``to_search_document()`` adds a ``_geo`` key with the Meilisearch-compatible
    format::

        "_geo": {"lat": 40.7128, "lng": -74.0060}

    Example using a combined attribute::

        class Venue(SearchableMixin, BaseModel):
            search_index_name = "venues"
            search_fields = ["name"]
            search_geo_field = "coordinates"  # returns (lat, lng)

            @property
            def coordinates(self) -> tuple[float, float]:
                return (self.latitude, self.longitude)

    Example using separate lat/lng fields::

        class Venue(SearchableMixin, BaseModel):
            search_geo_field = "location"   # not used — set to empty string
            search_lat_field = "latitude"
            search_lng_field = "longitude"

    Both ``search_lat_field`` / ``search_lng_field`` and ``search_geo_field``
    (returning a tuple) are supported.  ``search_lat_field`` / ``search_lng_field``
    take precedence.

    Soft-delete awareness
    ---------------------
    When ``search_exclude_soft_deleted`` is ``True`` (the default),
    ``get_search_queryset()`` automatically excludes soft-deleted records.
    Detection is by field presence:

    - ``is_deleted`` field (boolean) — records where ``is_deleted=True`` are
      excluded.
    - ``deleted_at`` field (datetime, nullable) — records where ``deleted_at``
      is not ``None`` are excluded.

    Set ``search_exclude_soft_deleted = False`` to opt out and return all
    records regardless of soft-delete state.
    """

    search_index_name: str = ""
    search_fields: list[str] = []
    search_filterable_fields: list[str] = []
    search_sortable_fields: list[str] = []
    search_displayed_fields: list[str] = []
    search_exclude_soft_deleted: bool = True

    # Geo search configuration.
    # Set search_lat_field + search_lng_field to the attribute names that hold
    # latitude and longitude respectively, OR set search_geo_field to an
    # attribute/property that returns a (lat, lng) tuple.
    # When either strategy is configured, to_search_document() will include a
    # ``_geo`` field in the output document.
    search_geo_field: str = ""
    search_lat_field: str = ""
    search_lng_field: str = ""

    def to_search_document(self) -> dict[str, Any]:
        """Convert this model instance to a search document dict.

        When ``search_lat_field`` and ``search_lng_field`` are both set, or
        when ``search_geo_field`` names an attribute returning a ``(lat, lng)``
        tuple, the document will include a ``_geo`` key in the format required
        by Meilisearch and consumed by the DummyBackend and PostgresBackend::

            {"_geo": {"lat": 51.5074, "lng": -0.1278}}

        Override for custom serialisation (e.g. to include related objects,
        format dates, or flatten nested data).
        """
        doc: dict[str, Any] = {"id": str(self.pk)}  # type: ignore[attr-defined]
        for field in self.search_fields:
            value = getattr(self, field, None)
            # Convert non-serialisable types
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            elif hasattr(value, "__str__") and not isinstance(value, (str, int, float, bool, type(None), list, dict)):
                value = str(value)
            doc[field] = value

        # Attach _geo field when geo configuration is present.
        if self.search_lat_field and self.search_lng_field:
            lat = getattr(self, self.search_lat_field, None)
            lng = getattr(self, self.search_lng_field, None)
            if lat is not None and lng is not None:
                try:
                    doc["_geo"] = {"lat": float(lat), "lng": float(lng)}
                except (TypeError, ValueError):
                    pass
        elif self.search_geo_field:
            geo_value = getattr(self, self.search_geo_field, None)
            if geo_value is not None:
                try:
                    lat, lng = geo_value
                    doc["_geo"] = {"lat": float(lat), "lng": float(lng)}
                except (TypeError, ValueError):
                    pass

        return doc

    @classmethod
    def get_search_queryset(cls):
        """Return the queryset used for full reindex.

        Automatically excludes soft-deleted records when
        ``search_exclude_soft_deleted`` is ``True`` (the default).

        Soft-delete detection is field-based:

        - ``is_deleted`` (boolean) — filters out records where
          ``is_deleted=True``.
        - ``deleted_at`` (nullable datetime) — filters out records where
          ``deleted_at`` is not ``None``.

        Override to customise filtering further or to add
        ``select_related``/``prefetch_related`` for performance.
        """
        qs = cls.objects.all()  # type: ignore[attr-defined]

        if not cls.search_exclude_soft_deleted:
            return qs

        # Inspect the concrete model's fields for soft-delete markers.
        try:
            field_names = {f.name for f in cls._meta.get_fields()}  # type: ignore[attr-defined]
        except AttributeError:
            # Not a Django model — return unfiltered.
            return qs

        if "is_deleted" in field_names:
            qs = qs.filter(is_deleted=False)

        if "deleted_at" in field_names:
            qs = qs.filter(deleted_at__isnull=True)

        return qs

    @classmethod
    def hydrate(cls, result, *, queryset=None):
        """Return a Django QuerySet from a :class:`~icv_search.types.SearchResult`, preserving search relevance order.

        Extracts document IDs from search hits, fetches the corresponding model
        instances from the database, and orders them to match the search engine's
        ranking using ``Case``/``When`` expressions.

        The returned QuerySet supports all standard ORM operations::

            result = search("products", "ergonomic chair")
            qs = Product.hydrate(result).select_related("category")

        Args:
            result: A :class:`~icv_search.types.SearchResult` (or
                :class:`~icv_search.types.MerchandisedSearchResult`).
            queryset: Optional base QuerySet.  Defaults to
                ``cls.get_search_queryset()``.  Pass a custom QuerySet to
                include ``select_related``/``prefetch_related`` or extra filters.

        Returns:
            A QuerySet of model instances in search-relevance order.
        """
        from django.db.models import Case, Value, When

        if queryset is None:
            queryset = cls.get_search_queryset()

        hit_ids = [hit.get("id") for hit in result.hits if hit.get("id") is not None]

        if not hit_ids:
            return queryset.none()

        ordering = Case(*[When(pk=pk_val, then=Value(pos)) for pos, pk_val in enumerate(hit_ids)])

        return queryset.filter(pk__in=hit_ids).order_by(ordering)
