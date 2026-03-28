"""Tests for the query rewrite service functions."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from icv_search.models.merchandising import QueryRewrite
from icv_search.services.rewrites import apply_rewrite


def _make_rewrite(**kwargs) -> QueryRewrite:
    """Create and save a QueryRewrite with sensible defaults."""
    defaults = {
        "index_name": "products",
        "tenant_id": "",
        "query_pattern": "trainers",
        "match_type": "exact",
        "rewritten_query": "running shoes",
        "apply_filters": {},
        "apply_sort": [],
        "is_active": True,
        "priority": 0,
    }
    defaults.update(kwargs)
    return QueryRewrite.objects.create(**defaults)


class TestApplyRewrite:
    """apply_rewrite() — rule matching and result tuple."""

    @pytest.mark.django_db
    def test_exact_match_rewrites_query(self):
        _make_rewrite(query_pattern="trainers", rewritten_query="running shoes")
        rewritten, _filters, _sort, rule = apply_rewrite("products", "trainers")
        assert rewritten == "running shoes"
        assert rule is not None

    @pytest.mark.django_db
    def test_no_match_returns_original_query(self):
        rewritten, filters, sort, rule = apply_rewrite("products", "boots")
        assert rewritten == "boots"
        assert filters == {}
        assert sort == []
        assert rule is None

    @pytest.mark.django_db
    def test_filters_returned_from_matched_rule(self):
        _make_rewrite(
            query_pattern="trainers",
            apply_filters={"category": "footwear", "in_stock": True},
        )
        _rewritten, filters, _sort, _rule = apply_rewrite("products", "trainers")
        assert filters == {"category": "footwear", "in_stock": True}

    @pytest.mark.django_db
    def test_sort_returned_from_matched_rule(self):
        _make_rewrite(
            query_pattern="trainers",
            apply_sort=["price:asc", "rating:desc"],
        )
        _rewritten, _filters, sort, _rule = apply_rewrite("products", "trainers")
        assert sort == ["price:asc", "rating:desc"]

    @pytest.mark.django_db
    def test_empty_filters_returns_empty_dict(self):
        _make_rewrite(query_pattern="trainers", apply_filters={})
        _rewritten, filters, _sort, _rule = apply_rewrite("products", "trainers")
        assert filters == {}

    @pytest.mark.django_db
    def test_empty_sort_returns_empty_list(self):
        _make_rewrite(query_pattern="trainers", apply_sort=[])
        _rewritten, _filters, sort, _rule = apply_rewrite("products", "trainers")
        assert sort == []

    @pytest.mark.django_db
    def test_merge_filters_attribute_present_on_rule(self):
        """merge_filters is a field on QueryRewrite — the matched rule exposes it."""
        _make_rewrite(query_pattern="trainers", merge_filters=True)
        _rewritten, _filters, _sort, rule = apply_rewrite("products", "trainers")
        assert rule is not None
        assert hasattr(rule, "merge_filters")
        assert rule.merge_filters is True

    @pytest.mark.django_db
    def test_no_cascading_only_highest_priority_applies(self):
        """Only one rewrite is returned even when multiple rules match."""
        _make_rewrite(
            query_pattern="trainers",
            priority=1,
            rewritten_query="low priority query",
        )
        _make_rewrite(
            query_pattern="trainers",
            priority=10,
            rewritten_query="high priority query",
        )
        rewritten, _filters, _sort, rule = apply_rewrite("products", "trainers")
        assert rewritten == "high priority query"
        assert rule is not None

    @pytest.mark.django_db
    def test_inactive_rule_is_skipped(self):
        _make_rewrite(query_pattern="trainers", is_active=False)
        rewritten, _filters, _sort, rule = apply_rewrite("products", "trainers")
        assert rewritten == "trainers"
        assert rule is None

    @pytest.mark.django_db
    def test_starts_at_in_future_is_skipped(self):
        _make_rewrite(
            query_pattern="trainers",
            starts_at=timezone.now() + timedelta(hours=1),
        )
        rewritten, _filters, _sort, rule = apply_rewrite("products", "trainers")
        assert rule is None
        assert rewritten == "trainers"

    @pytest.mark.django_db
    def test_ends_at_in_past_is_skipped(self):
        _make_rewrite(
            query_pattern="trainers",
            ends_at=timezone.now() - timedelta(hours=1),
        )
        rewritten, _filters, _sort, rule = apply_rewrite("products", "trainers")
        assert rule is None
        assert rewritten == "trainers"

    @pytest.mark.django_db
    def test_hit_count_incremented_on_match(self):
        rule = _make_rewrite(query_pattern="trainers", hit_count=0)
        apply_rewrite("products", "trainers")
        rule.refresh_from_db()
        assert rule.hit_count == 1

    @pytest.mark.django_db
    def test_tenant_specific_rule_matches(self):
        _make_rewrite(query_pattern="trainers", tenant_id="acme")
        rewritten, _filters, _sort, rule = apply_rewrite("products", "trainers", tenant_id="acme")
        assert rule is not None
        assert rewritten == "running shoes"

    @pytest.mark.django_db
    def test_non_matching_tenant_returns_no_match(self):
        _make_rewrite(query_pattern="trainers", tenant_id="acme")
        rewritten, _filters, _sort, rule = apply_rewrite("products", "trainers", tenant_id="other")
        assert rule is None
        assert rewritten == "trainers"

    @pytest.mark.django_db
    def test_contains_match_type_rewrites_query(self):
        _make_rewrite(
            query_pattern="train",
            match_type="contains",
            rewritten_query="running shoes",
        )
        rewritten, _filters, _sort, rule = apply_rewrite("products", "trainers")
        assert rule is not None
        assert rewritten == "running shoes"
