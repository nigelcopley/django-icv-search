"""Search merchandising models — rules for controlling search result presentation."""

from __future__ import annotations

import re

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from icv_search.models.base import BaseModel

MATCH_TYPE_CHOICES = [
    ("exact", _("Exact")),
    ("contains", _("Contains")),
    ("starts_with", _("Starts with")),
    ("regex", _("Regular expression")),
]


class MerchandisingRuleBase(BaseModel):
    """Abstract base for all merchandising rules.

    Provides common fields for query matching, scheduling, activation,
    and priority ordering. Concrete subclasses add rule-specific fields.
    """

    index_name = models.CharField(
        max_length=200,
        db_index=True,
        help_text=_("Logical index name this rule applies to."),
    )
    tenant_id = models.CharField(
        max_length=200,
        blank=True,
        default="",
        db_index=True,
        help_text=_("Tenant identifier. Blank applies to all tenants."),
    )
    query_pattern = models.CharField(
        max_length=500,
        help_text=_("Query pattern to match against incoming search queries."),
    )
    match_type = models.CharField(
        max_length=20,
        choices=MATCH_TYPE_CHOICES,
        default="exact",
        help_text=_("How query_pattern is compared to the search query."),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_("Inactive rules are never evaluated."),
    )
    priority = models.IntegerField(
        default=0,
        db_index=True,
        help_text=_("Higher priority rules are evaluated first."),
    )
    starts_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Rule is active from this date/time. Blank means no start constraint."),
    )
    ends_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Rule is active until this date/time. Blank means no end constraint."),
    )
    hit_count = models.PositiveIntegerField(
        default=0,
        help_text=_("Number of times this rule has been triggered."),
    )

    class Meta:
        abstract = True
        ordering = ["-priority", "-created_at"]

    def is_within_schedule(self) -> bool:
        """Return True if the current time falls within the rule's schedule window."""
        now = timezone.now()
        if self.starts_at and now < self.starts_at:
            return False
        return not (self.ends_at and now > self.ends_at)

    def matches_query(self, query: str) -> bool:
        """Return True if ``query`` matches this rule's pattern and match type.

        The comparison is case-insensitive. The query is stripped and lowered
        before matching.
        """
        normalised = query.strip().lower()
        pattern = self.query_pattern.strip().lower()

        if self.match_type == "exact":
            return normalised == pattern
        if self.match_type == "contains":
            return pattern in normalised
        if self.match_type == "starts_with":
            return normalised.startswith(pattern)
        if self.match_type == "regex":
            try:
                return bool(re.search(pattern, normalised))
            except re.error:
                return False
        return False


class QueryRedirect(MerchandisingRuleBase):
    """Redirect a search query to a specific URL instead of showing results."""

    DESTINATION_TYPE_CHOICES = [
        ("url", _("External URL")),
        ("category", _("Category page")),
        ("product", _("Product page")),
        ("page", _("CMS page")),
    ]

    HTTP_STATUS_CHOICES = [
        (301, _("301 Permanent")),
        (302, _("302 Temporary")),
    ]

    destination_url = models.URLField(
        max_length=2000,
        help_text=_("URL to redirect the user to."),
    )
    destination_type = models.CharField(
        max_length=20,
        choices=DESTINATION_TYPE_CHOICES,
        default="url",
        help_text=_("Type of destination for analytics tracking."),
    )
    preserve_query = models.BooleanField(
        default=False,
        help_text=_("Append the original query as a ?q= parameter to the destination URL."),
    )
    http_status = models.IntegerField(
        choices=HTTP_STATUS_CHOICES,
        default=302,
        help_text=_("HTTP status code for the redirect response."),
    )

    class Meta(MerchandisingRuleBase.Meta):
        verbose_name = _("query redirect")
        verbose_name_plural = _("query redirects")

    def __str__(self) -> str:
        return f"Redirect: {self.query_pattern!r} → {self.destination_url}"


class QueryRewrite(MerchandisingRuleBase):
    """Transparently rewrite a search query before execution."""

    rewritten_query = models.CharField(
        max_length=500,
        help_text=_("The query string to use instead of the original."),
    )
    apply_filters = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Additional filters to inject into the search request."),
    )
    apply_sort = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Sort order to inject into the search request."),
    )
    merge_filters = models.BooleanField(
        default=True,
        help_text=_("Merge injected filters with existing filters. When False, replaces them."),
    )

    class Meta(MerchandisingRuleBase.Meta):
        verbose_name = _("query rewrite")
        verbose_name_plural = _("query rewrites")

    def __str__(self) -> str:
        return f"Rewrite: {self.query_pattern!r} → {self.rewritten_query!r}"


class SearchPin(MerchandisingRuleBase):
    """Pin a specific document to a fixed position in search results."""

    document_id = models.CharField(
        max_length=255,
        help_text=_("ID of the document to pin."),
    )
    position = models.IntegerField(
        default=0,
        help_text=_("Zero-based position in results. Use -1 to bury (push to end)."),
    )
    label = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text=_("Optional label for the pin (e.g. 'sponsored', 'editorial pick')."),
    )

    class Meta(MerchandisingRuleBase.Meta):
        verbose_name = _("search pin")
        verbose_name_plural = _("search pins")
        constraints = [
            models.UniqueConstraint(
                fields=["index_name", "tenant_id", "query_pattern", "document_id"],
                name="icv_search_pin_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"Pin: doc {self.document_id} at position {self.position} for {self.query_pattern!r}"


class BoostRule(MerchandisingRuleBase):
    """Boost or demote search results based on field values."""

    OPERATOR_CHOICES = [
        ("eq", _("Equals")),
        ("neq", _("Not equals")),
        ("gt", _("Greater than")),
        ("gte", _("Greater than or equal")),
        ("lt", _("Less than")),
        ("lte", _("Less than or equal")),
        ("contains", _("Contains")),
        ("exists", _("Field exists")),
    ]

    field = models.CharField(
        max_length=200,
        help_text=_("Document field to evaluate."),
    )
    field_value = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text=_("Value to compare against. Ignored for 'exists' operator."),
    )
    operator = models.CharField(
        max_length=20,
        choices=OPERATOR_CHOICES,
        default="eq",
        help_text=_("Comparison operator."),
    )
    boost_weight = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=1.0,
        help_text=_(
            "Multiplicative weight. Values > 1 promote, values between 0 and 1 demote. "
            "Applied to the document's ranking score."
        ),
    )

    class Meta(MerchandisingRuleBase.Meta):
        verbose_name = _("boost rule")
        verbose_name_plural = _("boost rules")

    def __str__(self) -> str:
        return f"Boost: {self.field} {self.operator} {self.field_value!r} (×{self.boost_weight})"


class SearchBanner(MerchandisingRuleBase):
    """Display a banner alongside search results."""

    POSITION_CHOICES = [
        ("top", _("Top of results")),
        ("inline", _("Inline within results")),
        ("bottom", _("Bottom of results")),
        ("sidebar", _("Sidebar")),
    ]

    BANNER_TYPE_CHOICES = [
        ("informational", _("Informational")),
        ("promotional", _("Promotional")),
        ("warning", _("Warning")),
    ]

    title = models.CharField(
        max_length=200,
        help_text=_("Banner headline."),
    )
    content = models.TextField(
        blank=True,
        default="",
        help_text=_("Banner body content (supports HTML)."),
    )
    image_url = models.URLField(
        max_length=2000,
        blank=True,
        default="",
        help_text=_("Optional banner image URL."),
    )
    link_url = models.URLField(
        max_length=2000,
        blank=True,
        default="",
        help_text=_("Optional click-through URL."),
    )
    link_text = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text=_("Call-to-action text for the link."),
    )
    position = models.CharField(
        max_length=20,
        choices=POSITION_CHOICES,
        default="top",
        help_text=_("Where to display the banner relative to results."),
    )
    banner_type = models.CharField(
        max_length=20,
        choices=BANNER_TYPE_CHOICES,
        default="informational",
        help_text=_("Semantic type of the banner for styling."),
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Arbitrary metadata for custom rendering logic."),
    )

    class Meta(MerchandisingRuleBase.Meta):
        verbose_name = _("search banner")
        verbose_name_plural = _("search banners")

    def __str__(self) -> str:
        return f"Banner: {self.title} ({self.position})"


class ZeroResultFallback(MerchandisingRuleBase):
    """Define fallback behaviour when a search query returns no results."""

    FALLBACK_TYPE_CHOICES = [
        ("redirect", _("Redirect to URL")),
        ("alternative_query", _("Run alternative query")),
        ("curated_results", _("Show curated document IDs")),
        ("popular_in_category", _("Show popular items in category")),
    ]

    fallback_type = models.CharField(
        max_length=30,
        choices=FALLBACK_TYPE_CHOICES,
        help_text=_("Strategy to use when the original query returns zero results."),
    )
    fallback_value = models.CharField(
        max_length=2000,
        help_text=_(
            "Meaning depends on fallback_type: URL for redirect, query string for "
            "alternative_query, comma-separated IDs for curated_results, "
            "category identifier for popular_in_category."
        ),
    )
    fallback_filters = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Additional filters applied when executing the fallback search."),
    )
    max_retries = models.PositiveIntegerField(
        default=1,
        help_text=_("Maximum number of fallback attempts before giving up."),
    )

    class Meta(MerchandisingRuleBase.Meta):
        verbose_name = _("zero-result fallback")
        verbose_name_plural = _("zero-result fallbacks")

    def __str__(self) -> str:
        return f"Fallback: {self.fallback_type} for {self.query_pattern!r}"
