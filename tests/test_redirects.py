"""Tests for the query redirect service functions."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from icv_search.models.merchandising import QueryRedirect
from icv_search.services.redirects import check_redirect, resolve_redirect_url


def _make_redirect(**kwargs) -> QueryRedirect:
    """Create and save a QueryRedirect with sensible defaults."""
    defaults = {
        "index_name": "products",
        "tenant_id": "",
        "query_pattern": "shoes",
        "match_type": "exact",
        "destination_url": "https://example.com/shoes/",
        "is_active": True,
        "priority": 0,
    }
    defaults.update(kwargs)
    return QueryRedirect.objects.create(**defaults)


class TestCheckRedirect:
    """check_redirect() — rule matching and selection."""

    @pytest.mark.django_db
    def test_exact_match_returns_redirect(self):
        rule = _make_redirect(query_pattern="shoes", match_type="exact")
        result = check_redirect("products", "shoes")
        assert result is not None
        assert result.pk == rule.pk

    @pytest.mark.django_db
    def test_contains_match_returns_redirect(self):
        rule = _make_redirect(query_pattern="shoe", match_type="contains")
        result = check_redirect("products", "red shoes")
        assert result is not None
        assert result.pk == rule.pk

    @pytest.mark.django_db
    def test_starts_with_match_returns_redirect(self):
        rule = _make_redirect(query_pattern="run", match_type="starts_with")
        result = check_redirect("products", "running shoes")
        assert result is not None
        assert result.pk == rule.pk

    @pytest.mark.django_db
    def test_regex_match_returns_redirect(self):
        rule = _make_redirect(query_pattern=r"^shoe(s)?$", match_type="regex")
        result = check_redirect("products", "shoes")
        assert result is not None
        assert result.pk == rule.pk

    @pytest.mark.django_db
    def test_no_match_returns_none(self):
        _make_redirect(query_pattern="boots", match_type="exact")
        result = check_redirect("products", "sandals")
        assert result is None

    @pytest.mark.django_db
    def test_highest_priority_wins(self):
        low = _make_redirect(
            query_pattern="shoes",
            priority=1,
            destination_url="https://example.com/low/",
        )
        high = _make_redirect(
            query_pattern="shoes",
            priority=10,
            destination_url="https://example.com/high/",
        )
        result = check_redirect("products", "shoes")
        assert result is not None
        assert result.pk == high.pk
        assert result.pk != low.pk

    @pytest.mark.django_db
    def test_inactive_rule_is_skipped(self):
        _make_redirect(query_pattern="shoes", is_active=False)
        result = check_redirect("products", "shoes")
        assert result is None

    @pytest.mark.django_db
    def test_starts_at_in_future_is_skipped(self):
        _make_redirect(
            query_pattern="shoes",
            starts_at=timezone.now() + timedelta(hours=1),
        )
        result = check_redirect("products", "shoes")
        assert result is None

    @pytest.mark.django_db
    def test_ends_at_in_past_is_skipped(self):
        _make_redirect(
            query_pattern="shoes",
            ends_at=timezone.now() - timedelta(hours=1),
        )
        result = check_redirect("products", "shoes")
        assert result is None

    @pytest.mark.django_db
    def test_within_schedule_window_is_matched(self):
        rule = _make_redirect(
            query_pattern="shoes",
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(hours=1),
        )
        result = check_redirect("products", "shoes")
        assert result is not None
        assert result.pk == rule.pk

    @pytest.mark.django_db
    def test_hit_count_incremented_on_match(self):
        rule = _make_redirect(query_pattern="shoes", hit_count=0)
        check_redirect("products", "shoes")
        rule.refresh_from_db()
        assert rule.hit_count == 1

    @pytest.mark.django_db
    def test_tenant_specific_rule_matches(self):
        rule = _make_redirect(query_pattern="shoes", tenant_id="acme")
        result = check_redirect("products", "shoes", tenant_id="acme")
        assert result is not None
        assert result.pk == rule.pk

    @pytest.mark.django_db
    def test_tenant_specific_rule_does_not_match_different_tenant(self):
        _make_redirect(query_pattern="shoes", tenant_id="acme")
        result = check_redirect("products", "shoes", tenant_id="other")
        assert result is None

    @pytest.mark.django_db
    def test_global_rule_matches_when_tenant_provided(self):
        """A rule with blank tenant_id applies to all tenants."""
        rule = _make_redirect(query_pattern="shoes", tenant_id="")
        result = check_redirect("products", "shoes", tenant_id="acme")
        assert result is not None
        assert result.pk == rule.pk

    @pytest.mark.django_db
    def test_returns_none_when_no_rules_exist(self):
        result = check_redirect("products", "shoes")
        assert result is None


class TestResolveRedirectUrl:
    """resolve_redirect_url() — URL construction."""

    def test_without_preserve_query_returns_destination_unchanged(self):
        rule = QueryRedirect(
            destination_url="https://example.com/shoes/",
            preserve_query=False,
        )
        url = resolve_redirect_url(rule, "shoes")
        assert url == "https://example.com/shoes/"

    def test_with_preserve_query_appends_q_parameter(self):
        rule = QueryRedirect(
            destination_url="https://example.com/search/",
            preserve_query=True,
        )
        url = resolve_redirect_url(rule, "red shoes")
        assert "q=red+shoes" in url or "q=red%20shoes" in url

    def test_with_preserve_query_and_existing_params(self):
        rule = QueryRedirect(
            destination_url="https://example.com/search/?category=footwear",
            preserve_query=True,
        )
        url = resolve_redirect_url(rule, "trainers")
        assert "category=footwear" in url
        assert "q=trainers" in url

    def test_preserve_query_false_with_empty_query(self):
        rule = QueryRedirect(
            destination_url="https://example.com/shoes/",
            preserve_query=False,
        )
        url = resolve_redirect_url(rule, "")
        assert url == "https://example.com/shoes/"

    def test_preserve_query_true_with_empty_query_returns_url_unchanged(self):
        """When preserve_query is True but query is empty, the URL is not modified."""
        rule = QueryRedirect(
            destination_url="https://example.com/shoes/",
            preserve_query=True,
        )
        url = resolve_redirect_url(rule, "")
        assert url == "https://example.com/shoes/"
