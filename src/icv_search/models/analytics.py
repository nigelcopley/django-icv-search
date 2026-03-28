"""Search query log model for analytics and debugging."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from icv_search.models.base import BaseModel


class SearchQueryLog(BaseModel):
    """Logs every search query for analytics and debugging.

    When ``ICV_SEARCH_LOG_QUERIES`` is ``True`` the :func:`~icv_search.services.search`
    function creates one record per call.  Set ``ICV_SEARCH_LOG_ZERO_RESULTS_ONLY``
    to ``True`` to limit storage to queries that returned no hits.
    """

    index_name = models.CharField(
        max_length=200,
        db_index=True,
        verbose_name=_("index name"),
        help_text=_("Logical search index name (e.g. 'products')."),
    )
    query = models.CharField(
        max_length=500,
        verbose_name=_("query"),
        help_text=_("The search query string submitted by the user."),
    )
    filters = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("filters"),
        help_text=_("Filter parameters passed to the search engine."),
    )
    sort = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("sort"),
        help_text=_("Sort parameters passed to the search engine."),
    )
    hit_count = models.IntegerField(
        default=0,
        verbose_name=_("hit count"),
        help_text=_("Number of results returned by the engine."),
    )
    processing_time_ms = models.IntegerField(
        default=0,
        verbose_name=_("processing time (ms)"),
        help_text=_("Time taken by the search engine to process the query."),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="search_query_logs",
        verbose_name=_("user"),
        help_text=_("Authenticated user who made the query, if any."),
    )
    tenant_id = models.CharField(
        max_length=200,
        default="",
        blank=True,
        db_index=True,
        verbose_name=_("tenant ID"),
        help_text=_("Tenant identifier for multi-tenant setups."),
    )
    is_zero_result = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("zero result"),
        help_text=_("True when the query returned no hits."),
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("metadata"),
        help_text=_("Extra context such as source page, session ID, or A/B test variant."),
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("search query log")
        verbose_name_plural = _("search query logs")
        indexes = [
            models.Index(fields=["index_name", "is_zero_result"]),
            models.Index(fields=["index_name", "tenant_id", "created_at"]),
        ]

    def __str__(self) -> str:
        return f'"{self.query}" on {self.index_name} ({self.hit_count} hits)'
