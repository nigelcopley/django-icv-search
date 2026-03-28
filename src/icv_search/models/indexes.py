"""Search index and sync log models."""

from __future__ import annotations

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from icv_search.models.base import BaseModel


class SearchIndex(BaseModel):
    """Represents a search index in the configured search engine.

    The engine_uid is computed automatically from the index prefix, tenant ID,
    and logical name. Django is the source of truth for index configuration;
    settings are pushed to the engine via sync tasks.
    """

    name = models.CharField(
        max_length=100,
        db_index=True,
        help_text=_("Logical index name (e.g. 'products')."),
    )
    tenant_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_index=True,
        help_text=_("Tenant identifier for multi-tenant setups. Blank in single-tenant mode."),
    )
    engine_uid = models.CharField(
        max_length=255,
        unique=True,
        editable=False,
        help_text=_("Computed index name sent to the search engine."),
    )
    primary_key_field = models.CharField(
        max_length=100,
        default="id",
        help_text=_("Document field used as the primary key in the search engine."),
    )
    settings = models.JSONField(
        default=dict,
        blank=True,
        help_text=_(
            "Engine settings: searchable_attributes, filterable_attributes, "
            "sortable_attributes, synonyms, stop_words, ranking_rules."
        ),
    )
    document_count = models.PositiveIntegerField(
        default=0,
        help_text=_("Cached document count, updated by refresh task."),
    )
    is_synced = models.BooleanField(
        default=False,
        help_text=_("Whether current settings have been pushed to the engine."),
    )
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Timestamp of last successful settings sync."),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_("Deactivated indexes are not queried or synced."),
    )

    class Meta:
        unique_together = [("tenant_id", "name")]
        ordering = ["name"]
        verbose_name = _("search index")
        verbose_name_plural = _("search indexes")

    def __str__(self) -> str:
        if self.tenant_id:
            return f"{self.name} (tenant: {self.tenant_id})"
        return self.name

    def save(self, *args, **kwargs):
        """Compute engine_uid before saving."""
        self.engine_uid = self._compute_engine_uid()
        super().save(*args, **kwargs)

    def _compute_engine_uid(self) -> str:
        """Build the engine-facing index name.

        Resolution order for the tenant segment:
        1. ``self.tenant_id`` if explicitly set on the instance.
        2. The return value of ``ICV_SEARCH_TENANT_PREFIX_FUNC`` (called with
           ``None`` because there is no request context at save time).
        3. No tenant segment (single-tenant mode).
        """
        from django.conf import settings as django_settings

        # Read at call time so that pytest settings fixture overrides take effect
        prefix = getattr(django_settings, "ICV_SEARCH_INDEX_PREFIX", "")
        tenant = self.tenant_id

        if not tenant:
            tenant_func_path: str = getattr(django_settings, "ICV_SEARCH_TENANT_PREFIX_FUNC", "")
            if tenant_func_path:
                from django.utils.module_loading import import_string

                func = import_string(tenant_func_path)
                tenant = func(None) or ""

        if tenant:
            return f"{prefix}{tenant}_{self.name}"
        return f"{prefix}{self.name}"

    def mark_synced(self) -> None:
        """Mark this index as synced with the engine."""
        self.is_synced = True
        self.last_synced_at = timezone.now()
        # Use update() to avoid triggering save() signal again
        SearchIndex.objects.filter(pk=self.pk).update(
            is_synced=True,
            last_synced_at=self.last_synced_at,
        )


class IndexSyncLog(BaseModel):
    """Log entry for search index synchronisation operations."""

    ACTION_CHOICES = [
        ("created", _("Created")),
        ("settings_updated", _("Settings Updated")),
        ("deleted", _("Deleted")),
        ("reindexed", _("Reindexed")),
        ("documents_added", _("Documents Added")),
        ("documents_deleted", _("Documents Deleted")),
    ]

    STATUS_CHOICES = [
        ("pending", _("Pending")),
        ("success", _("Success")),
        ("failed", _("Failed")),
    ]

    index = models.ForeignKey(
        SearchIndex,
        on_delete=models.CASCADE,
        related_name="sync_logs",
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    detail = models.TextField(blank=True, help_text=_("Error messages or sync metadata."))
    task_uid = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Engine-side task ID for async operations."),
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("index sync log")
        verbose_name_plural = _("index sync logs")

    def __str__(self) -> str:
        return f"{self.index.name} — {self.action} ({self.status})"

    def mark_complete(self, status: str = "success", detail: str = "") -> None:
        """Mark this log entry as complete."""
        self.status = status
        self.detail = detail
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "detail", "completed_at", "updated_at"])
