"""Add SearchClick and SearchClickAggregate models for click-through tracking (FEAT-008)."""

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("icv_search", "0004_merchandising"),
    ]

    operations = [
        migrations.CreateModel(
            name="SearchClick",
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
                        help_text="The search query string that produced the result page.",
                        max_length=500,
                        verbose_name="query",
                    ),
                ),
                (
                    "document_id",
                    models.CharField(
                        db_index=True,
                        help_text="Identifier of the document that was clicked.",
                        max_length=500,
                        verbose_name="document ID",
                    ),
                ),
                (
                    "position",
                    models.PositiveSmallIntegerField(
                        help_text="Zero-based position of the clicked document in the result list.",
                        verbose_name="position",
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
                    "metadata",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Extra context such as source page, session ID, or A/B test variant.",
                        verbose_name="metadata",
                    ),
                ),
            ],
            options={
                "verbose_name": "search click",
                "verbose_name_plural": "search clicks",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="SearchClickAggregate",
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
                    "document_id",
                    models.CharField(
                        db_index=True,
                        help_text="Identifier of the document that was clicked.",
                        max_length=500,
                        verbose_name="document ID",
                    ),
                ),
                (
                    "date",
                    models.DateField(
                        db_index=True,
                        help_text="Calendar date on which these clicks occurred.",
                        verbose_name="date",
                    ),
                ),
                (
                    "click_count",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Total number of clicks on this document for this query on this date.",
                        verbose_name="click count",
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
            ],
            options={
                "verbose_name": "search click aggregate",
                "verbose_name_plural": "search click aggregates",
                "ordering": ["-date"],
            },
        ),
        # Indexes for SearchClick
        migrations.AddIndex(
            model_name="searchclick",
            index=models.Index(
                fields=["index_name", "query", "created_at"],
                name="icv_srch_clk_qry_dt",
            ),
        ),
        migrations.AddIndex(
            model_name="searchclick",
            index=models.Index(
                fields=["index_name", "document_id"],
                name="icv_srch_clk_doc",
            ),
        ),
        # Indexes and constraints for SearchClickAggregate
        migrations.AddConstraint(
            model_name="searchclickaggregate",
            constraint=models.UniqueConstraint(
                fields=["index_name", "query", "document_id", "date", "tenant_id"],
                name="icv_search_click_agg_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="searchclickaggregate",
            index=models.Index(
                fields=["index_name", "query", "date"],
                name="icv_srch_clkagg_qry_dt",
            ),
        ),
        migrations.AddIndex(
            model_name="searchclickaggregate",
            index=models.Index(
                fields=["index_name", "date", "tenant_id"],
                name="icv_srch_clkagg_tnt_dt",
            ),
        ),
    ]
