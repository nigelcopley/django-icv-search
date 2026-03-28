"""Aggregate search query counters for high-volume analytics."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from icv_search.models.base import BaseModel


class SearchQueryAggregate(BaseModel):
    """Aggregated search query counters keyed on (index_name, query, date, tenant_id).

    Rather than storing one row per search call, this model accumulates counts and
    timing totals so dashboards can read a single row instead of aggregating millions
    of :class:`~icv_search.models.SearchQueryLog` rows.

    Use ``ICV_SEARCH_LOG_MODE = "aggregate"`` (or ``"both"``) to populate this table.
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
        help_text=_("Normalised (lowercased) search query string."),
    )
    date = models.DateField(
        db_index=True,
        verbose_name=_("date"),
        help_text=_("Calendar date on which these queries were made."),
    )
    tenant_id = models.CharField(
        max_length=200,
        default="",
        blank=True,
        db_index=True,
        verbose_name=_("tenant ID"),
        help_text=_("Tenant identifier for multi-tenant setups."),
    )
    total_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("total count"),
        help_text=_("Total number of times this query was executed on this date."),
    )
    zero_result_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("zero result count"),
        help_text=_("Number of executions that returned no hits."),
    )
    total_processing_time_ms = models.PositiveBigIntegerField(
        default=0,
        verbose_name=_("total processing time (ms)"),
        help_text=_("Sum of all per-query processing times for this aggregate row."),
    )

    class Meta:
        ordering = ["-date"]
        verbose_name = _("search query aggregate")
        verbose_name_plural = _("search query aggregates")
        constraints = [
            models.UniqueConstraint(
                fields=["index_name", "query", "date", "tenant_id"],
                name="icv_search_agg_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["index_name", "date"], name="icv_srch_agg_idx_dt"),
            models.Index(
                fields=["index_name", "tenant_id", "date"],
                name="icv_srch_agg_tnt_dt",
            ),
        ]

    def __str__(self) -> str:
        return f'"{self.query}" on {self.index_name} ({self.date})'

    @property
    def avg_processing_time_ms(self) -> float:
        """Average processing time in milliseconds across all executions in this row."""
        if self.total_count > 0:
            return self.total_processing_time_ms / self.total_count
        return 0.0
