# Generated migration for SearchQueryLog model.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("icv_search", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SearchQueryLog",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="created at"),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="updated at"),
                ),
                (
                    "index_name",
                    models.CharField(
                        db_index=True,
                        help_text="Logical search index name (e.g. 'products').",
                        max_length=200,
                        verbose_name="index name",
                    ),
                ),
                (
                    "query",
                    models.CharField(
                        help_text="The search query string submitted by the user.",
                        max_length=500,
                        verbose_name="query",
                    ),
                ),
                (
                    "filters",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Filter parameters passed to the search engine.",
                        verbose_name="filters",
                    ),
                ),
                (
                    "sort",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Sort parameters passed to the search engine.",
                        verbose_name="sort",
                    ),
                ),
                (
                    "hit_count",
                    models.IntegerField(
                        default=0,
                        help_text="Number of results returned by the engine.",
                        verbose_name="hit count",
                    ),
                ),
                (
                    "processing_time_ms",
                    models.IntegerField(
                        default=0,
                        help_text="Time taken by the search engine to process the query.",
                        verbose_name="processing time (ms)",
                    ),
                ),
                (
                    "tenant_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="Tenant identifier for multi-tenant setups.",
                        max_length=200,
                        verbose_name="tenant ID",
                    ),
                ),
                (
                    "is_zero_result",
                    models.BooleanField(
                        db_index=True,
                        default=False,
                        help_text="True when the query returned no hits.",
                        verbose_name="zero result",
                    ),
                ),
                (
                    "metadata",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Extra context such as source page, session ID, or A/B test variant.",
                        verbose_name="metadata",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        help_text="Authenticated user who made the query, if any.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="search_query_logs",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="user",
                    ),
                ),
            ],
            options={
                "verbose_name": "search query log",
                "verbose_name_plural": "search query logs",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="searchquerylog",
            index=models.Index(fields=["index_name", "is_zero_result"], name="icv_search__index_n_zero_idx"),
        ),
        migrations.AddIndex(
            model_name="searchquerylog",
            index=models.Index(
                fields=["index_name", "tenant_id", "created_at"],
                name="icv_search__index_n_tenant_idx",
            ),
        ),
    ]
