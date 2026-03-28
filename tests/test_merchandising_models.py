"""Tests for the merchandising models.

Covers MerchandisingRuleBase behaviour (via QueryRedirect as the concrete
vehicle) and model-specific fields / constraints for all six rule types.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.utils import timezone

from icv_search.models.merchandising import (
    BoostRule,
    QueryRedirect,
    QueryRewrite,
    SearchBanner,
    SearchPin,
    ZeroResultFallback,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_BASE = {
    "index_name": "products",
    "tenant_id": "",
    "query_pattern": "shoes",
    "match_type": "exact",
    "is_active": True,
    "priority": 0,
}


def _redirect(**kwargs) -> QueryRedirect:
    params = {**_BASE, "destination_url": "https://example.com/shoes/", **kwargs}
    return QueryRedirect.objects.create(**params)


# ---------------------------------------------------------------------------
# __str__ representations
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStrRepresentations:
    """Each model's __str__ method returns a meaningful string."""

    def test_query_redirect_str(self):
        rule = _redirect(query_pattern="boots", destination_url="https://example.com/boots/")
        assert "boots" in str(rule)
        assert "https://example.com/boots/" in str(rule)

    def test_query_rewrite_str(self):
        rule = QueryRewrite.objects.create(
            **{**_BASE, "rewritten_query": "trainers"},
        )
        assert "shoes" in str(rule)
        assert "trainers" in str(rule)

    def test_search_pin_str(self):
        rule = SearchPin.objects.create(
            **{**_BASE, "document_id": "doc-42", "position": 1},
        )
        assert "doc-42" in str(rule)
        assert "1" in str(rule)

    def test_boost_rule_str(self):
        rule = BoostRule.objects.create(
            **{**_BASE, "field": "brand", "field_value": "Nike", "boost_weight": Decimal("2.5")},
        )
        assert "brand" in str(rule)
        assert "Nike" in str(rule)

    def test_search_banner_str(self):
        rule = SearchBanner.objects.create(
            **{**_BASE, "title": "Summer Sale"},
        )
        assert "Summer Sale" in str(rule)

    def test_zero_result_fallback_str(self):
        rule = ZeroResultFallback.objects.create(
            **{
                **_BASE,
                "fallback_type": "alternative_query",
                "fallback_value": "sneakers",
            },
        )
        assert "alternative_query" in str(rule)
        assert "shoes" in str(rule)


# ---------------------------------------------------------------------------
# is_within_schedule()
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIsWithinSchedule:
    """is_within_schedule() evaluates the starts_at / ends_at window correctly."""

    def test_no_constraints_returns_true(self):
        rule = _redirect(starts_at=None, ends_at=None)
        assert rule.is_within_schedule() is True

    def test_starts_at_in_future_returns_false(self):
        rule = _redirect(starts_at=timezone.now() + timedelta(hours=1))
        assert rule.is_within_schedule() is False

    def test_starts_at_in_past_returns_true(self):
        rule = _redirect(starts_at=timezone.now() - timedelta(hours=1))
        assert rule.is_within_schedule() is True

    def test_ends_at_in_past_returns_false(self):
        rule = _redirect(ends_at=timezone.now() - timedelta(hours=1))
        assert rule.is_within_schedule() is False

    def test_ends_at_in_future_returns_true(self):
        rule = _redirect(ends_at=timezone.now() + timedelta(hours=1))
        assert rule.is_within_schedule() is True

    def test_within_window_returns_true(self):
        rule = _redirect(
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(hours=1),
        )
        assert rule.is_within_schedule() is True

    def test_outside_window_both_future_returns_false(self):
        """When both starts_at and ends_at are in the future, rule is not yet active."""
        rule = _redirect(
            starts_at=timezone.now() + timedelta(hours=1),
            ends_at=timezone.now() + timedelta(hours=2),
        )
        assert rule.is_within_schedule() is False


# ---------------------------------------------------------------------------
# matches_query()
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMatchesQuery:
    """matches_query() covers all four match types plus edge cases."""

    def test_exact_match_returns_true(self):
        rule = _redirect(query_pattern="shoes", match_type="exact")
        assert rule.matches_query("shoes") is True

    def test_exact_match_non_matching_query_returns_false(self):
        rule = _redirect(query_pattern="shoes", match_type="exact")
        assert rule.matches_query("shoe") is False

    def test_exact_match_case_insensitive(self):
        rule = _redirect(query_pattern="Shoes", match_type="exact")
        assert rule.matches_query("SHOES") is True

    def test_contains_match(self):
        rule = _redirect(query_pattern="shoe", match_type="contains")
        assert rule.matches_query("red shoes") is True
        assert rule.matches_query("boots") is False

    def test_starts_with_match(self):
        rule = _redirect(query_pattern="run", match_type="starts_with")
        assert rule.matches_query("running shoes") is True
        assert rule.matches_query("long run") is False

    def test_regex_match(self):
        rule = _redirect(query_pattern=r"^shoe(s)?$", match_type="regex")
        assert rule.matches_query("shoe") is True
        assert rule.matches_query("shoes") is True
        assert rule.matches_query("old shoes") is False

    def test_regex_invalid_pattern_returns_false(self):
        """An invalid regex must return False rather than raising an exception."""
        rule = _redirect(query_pattern="[invalid(", match_type="regex")
        assert rule.matches_query("anything") is False

    def test_matches_query_strips_leading_trailing_whitespace(self):
        """Queries are stripped before comparison."""
        rule = _redirect(query_pattern="shoes", match_type="exact")
        assert rule.matches_query("  shoes  ") is True


# ---------------------------------------------------------------------------
# Model-specific field defaults and constraints
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestQueryRedirectDefaults:
    """QueryRedirect model-specific field defaults."""

    def test_default_destination_type_is_url(self):
        rule = _redirect()
        assert rule.destination_type == "url"

    def test_default_preserve_query_is_false(self):
        rule = _redirect()
        assert rule.preserve_query is False

    def test_default_http_status_is_302(self):
        rule = _redirect()
        assert rule.http_status == 302


@pytest.mark.django_db
class TestQueryRewriteJsonDefaults:
    """QueryRewrite JSON field defaults are correct types."""

    def test_apply_filters_defaults_to_empty_dict(self):
        rule = QueryRewrite.objects.create(**{**_BASE, "rewritten_query": "trainers"})
        assert rule.apply_filters == {}

    def test_apply_sort_defaults_to_empty_list(self):
        rule = QueryRewrite.objects.create(**{**_BASE, "rewritten_query": "trainers"})
        assert rule.apply_sort == []

    def test_merge_filters_defaults_to_true(self):
        rule = QueryRewrite.objects.create(**{**_BASE, "rewritten_query": "trainers"})
        assert rule.merge_filters is True


@pytest.mark.django_db
class TestSearchPinUniqueConstraint:
    """SearchPin enforces a unique constraint on (index_name, tenant_id, query_pattern, document_id)."""

    def test_duplicate_pin_raises_integrity_error(self):
        pin_data = {**_BASE, "document_id": "doc-1", "position": 0}
        SearchPin.objects.create(**pin_data)
        with pytest.raises(IntegrityError):
            SearchPin.objects.create(**pin_data)

    def test_same_document_different_query_pattern_is_allowed(self):
        SearchPin.objects.create(**{**_BASE, "query_pattern": "shoes", "document_id": "doc-1"})
        # Different query_pattern — must not raise
        SearchPin.objects.create(**{**_BASE, "query_pattern": "boots", "document_id": "doc-1"})


@pytest.mark.django_db
class TestBoostRuleDecimalWeight:
    """BoostRule.boost_weight stores and retrieves Decimal values accurately."""

    def test_boost_weight_stored_as_decimal(self):
        rule = BoostRule.objects.create(
            **{**_BASE, "field": "rating", "boost_weight": Decimal("1.500")},
        )
        rule.refresh_from_db()
        assert isinstance(rule.boost_weight, Decimal)

    def test_boost_weight_value_is_preserved(self):
        rule = BoostRule.objects.create(
            **{**_BASE, "field": "rating", "boost_weight": Decimal("0.250")},
        )
        rule.refresh_from_db()
        assert rule.boost_weight == Decimal("0.250")

    def test_boost_weight_default_is_one(self):
        rule = BoostRule.objects.create(**{**_BASE, "field": "popularity"})
        assert rule.boost_weight == Decimal("1.0")


@pytest.mark.django_db
class TestSearchBannerMetadataJson:
    """SearchBanner.metadata stores arbitrary JSON data."""

    def test_metadata_defaults_to_empty_dict(self):
        rule = SearchBanner.objects.create(**{**_BASE, "title": "Promo"})
        assert rule.metadata == {}

    def test_metadata_stores_and_retrieves_nested_dict(self):
        payload = {"campaign_id": "xmas-2025", "tracking": {"utm_source": "search"}}
        rule = SearchBanner.objects.create(**{**_BASE, "title": "Xmas", "metadata": payload})
        rule.refresh_from_db()
        assert rule.metadata == payload


@pytest.mark.django_db
class TestZeroResultFallbackChoices:
    """ZeroResultFallback.fallback_type accepts all valid choices."""

    @pytest.mark.parametrize(
        "fallback_type",
        ["redirect", "alternative_query", "curated_results", "popular_in_category"],
    )
    def test_fallback_type_valid_choices(self, fallback_type):
        rule = ZeroResultFallback.objects.create(
            **{
                **_BASE,
                "fallback_type": fallback_type,
                "fallback_value": "value",
            }
        )
        rule.refresh_from_db()
        assert rule.fallback_type == fallback_type


# ---------------------------------------------------------------------------
# Default ordering
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDefaultOrdering:
    """Rules are returned ordered by -priority, -created_at by default."""

    def test_higher_priority_rule_comes_first(self):
        low = _redirect(query_pattern="shoes", priority=1, destination_url="https://example.com/a/")
        high = _redirect(query_pattern="boots", priority=10, destination_url="https://example.com/b/")
        rules = list(QueryRedirect.objects.all())
        assert rules[0].pk == high.pk
        assert rules[1].pk == low.pk
