"""Test models for icv-search."""

from django.db import models

from icv_search.mixins import SearchableMixin
from icv_search.models.base import BaseModel


class Article(SearchableMixin, BaseModel):
    """Test model using SearchableMixin."""

    search_index_name = "articles"
    search_fields = ["title", "body", "author"]
    search_filterable_fields = ["author", "is_published"]
    search_sortable_fields = ["created_at"]

    title = models.CharField(max_length=200)
    body = models.TextField(default="")
    author = models.CharField(max_length=100, default="")
    is_published = models.BooleanField(default=True)

    class Meta:
        app_label = "search_testapp"

    def __str__(self) -> str:
        return self.title


class SoftDeleteIsDeletedArticle(SearchableMixin, BaseModel):
    """Test model with ``is_deleted`` soft-delete field."""

    search_index_name = "soft_delete_articles"
    search_fields = ["title"]

    title = models.CharField(max_length=200)
    is_deleted = models.BooleanField(default=False, db_index=True)

    class Meta:
        app_label = "search_testapp"

    def __str__(self) -> str:
        return self.title


class SoftDeleteDeletedAtArticle(SearchableMixin, BaseModel):
    """Test model with ``deleted_at`` soft-delete field."""

    search_index_name = "deleted_at_articles"
    search_fields = ["title"]

    title = models.CharField(max_length=200)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "search_testapp"

    def __str__(self) -> str:
        return self.title


class NoSoftDeleteArticle(SearchableMixin, BaseModel):
    """Test model with no soft-delete fields at all."""

    search_index_name = "no_soft_delete_articles"
    search_fields = ["title"]
    search_exclude_soft_deleted = False

    title = models.CharField(max_length=200)

    class Meta:
        app_label = "search_testapp"

    def __str__(self) -> str:
        return self.title


class OptOutSoftDeleteArticle(SearchableMixin, BaseModel):
    """Test model with is_deleted but search_exclude_soft_deleted=False."""

    search_index_name = "opt_out_articles"
    search_fields = ["title"]
    search_exclude_soft_deleted = False

    title = models.CharField(max_length=200)
    is_deleted = models.BooleanField(default=False, db_index=True)

    class Meta:
        app_label = "search_testapp"

    def __str__(self) -> str:
        return self.title


class GeoVenue(SearchableMixin, BaseModel):
    """Test model using separate lat/lng fields for geo search."""

    search_index_name = "venues"
    search_fields = ["name"]
    search_lat_field = "latitude"
    search_lng_field = "longitude"

    name = models.CharField(max_length=200)
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        app_label = "search_testapp"

    def __str__(self) -> str:
        return self.name


class GeoVenueWithProperty(SearchableMixin, BaseModel):
    """Test model using a property tuple for geo search."""

    search_index_name = "venues_property"
    search_fields = ["name"]
    search_geo_field = "coordinates"

    name = models.CharField(max_length=200)
    lat = models.FloatField()
    lng = models.FloatField()

    class Meta:
        app_label = "search_testapp"

    def __str__(self) -> str:
        return self.name

    @property
    def coordinates(self) -> tuple[float, float]:
        """Return ``(lat, lng)`` tuple for geo indexing."""
        return (self.lat, self.lng)
