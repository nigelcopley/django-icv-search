# Generated migration for SearchQueryAggregate model.

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("icv_search", "0002_searchquerylog"),
    ]

    operations = [
        migrations.CreateModel(
            name="SearchQueryAggregate",
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
                        help_text="Normalised (lowercased) search query string.",
                        max_length=500,
                        verbose_name="query",
                    ),
                ),
                (
                    "date",
                    models.DateField(
                        db_index=True,
                        help_text="Calendar date on which these queries were made.",
                        verbose_name="date",
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
                    "total_count",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Total number of times this query was executed on this date.",
                        verbose_name="total count",
                    ),
                ),
                (
                    "zero_result_count",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Number of executions that returned no hits.",
                        verbose_name="zero result count",
                    ),
                ),
                (
                    "total_processing_time_ms",
                    models.PositiveBigIntegerField(
                        default=0,
                        help_text="Sum of all per-query processing times for this aggregate row.",
                        verbose_name="total processing time (ms)",
                    ),
                ),
            ],
            options={
                "verbose_name": "search query aggregate",
                "verbose_name_plural": "search query aggregates",
                "ordering": ["-date"],
            },
        ),
        migrations.AddConstraint(
            model_name="searchqueryaggregate",
            constraint=models.UniqueConstraint(
                fields=["index_name", "query", "date", "tenant_id"],
                name="icv_search_agg_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="searchqueryaggregate",
            index=models.Index(
                fields=["index_name", "date"],
                name="icv_srch_agg_idx_dt",
            ),
        ),
        migrations.AddIndex(
            model_name="searchqueryaggregate",
            index=models.Index(
                fields=["index_name", "tenant_id", "date"],
                name="icv_srch_agg_tnt_dt",
            ),
        ),
    ]
