"""Tests for the search banner service functions."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from icv_search.models.merchandising import SearchBanner
from icv_search.services.banners import get_banners_for_query


@pytest.fixture(autouse=True)
def disable_merch_cache(settings):
    """Disable the merchandising rule cache so DB rollbacks take effect between tests."""
    settings.ICV_SEARCH_MERCHANDISING_CACHE_TIMEOUT = 0


def _make_banner(**kwargs) -> SearchBanner:
    """Create and save a SearchBanner with sensible defaults."""
    defaults = {
        "index_name": "products",
        "tenant_id": "",
        "query_pattern": "shoes",
        "match_type": "exact",
        "title": "Great Shoes Sale",
        "is_active": True,
        "priority": 0,
    }
    defaults.update(kwargs)
    return SearchBanner.objects.create(**defaults)


class TestGetBannersForQuery:
    """get_banners_for_query() — rule matching and selection."""

    @pytest.mark.django_db
    def test_returns_matching_banner_for_exact_query(self):
        banner = _make_banner(query_pattern="shoes", match_type="exact")
        result = get_banners_for_query("products", "shoes")
        assert len(result) == 1
        assert result[0].pk == banner.pk

    @pytest.mark.django_db
    def test_returns_multiple_banners_for_same_query(self):
        banner_a = _make_banner(title="Banner A", priority=5)
        banner_b = _make_banner(title="Banner B", priority=3)
        result = get_banners_for_query("products", "shoes")
        pks = [b.pk for b in result]
        assert banner_a.pk in pks
        assert banner_b.pk in pks
        assert len(result) == 2

    @pytest.mark.django_db
    def test_no_match_returns_empty_list(self):
        _make_banner(query_pattern="boots", match_type="exact")
        result = get_banners_for_query("products", "sandals")
        assert result == []

    @pytest.mark.django_db
    def test_starts_at_in_future_is_skipped(self):
        _make_banner(
            query_pattern="shoes",
            starts_at=timezone.now() + timedelta(hours=1),
        )
        result = get_banners_for_query("products", "shoes")
        assert result == []

    @pytest.mark.django_db
    def test_ends_at_in_past_is_skipped(self):
        _make_banner(
            query_pattern="shoes",
            ends_at=timezone.now() - timedelta(hours=1),
        )
        result = get_banners_for_query("products", "shoes")
        assert result == []

    @pytest.mark.django_db
    def test_within_schedule_window_is_matched(self):
        banner = _make_banner(
            query_pattern="shoes",
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(hours=1),
        )
        result = get_banners_for_query("products", "shoes")
        assert len(result) == 1
        assert result[0].pk == banner.pk

    @pytest.mark.django_db
    def test_priority_ordering_highest_first(self):
        low = _make_banner(title="Low", priority=1)
        high = _make_banner(title="High", priority=10)
        result = get_banners_for_query("products", "shoes")
        # Highest priority banner should come first (model ordering: -priority)
        assert result[0].pk == high.pk
        assert result[1].pk == low.pk

    @pytest.mark.django_db
    def test_inactive_banner_is_skipped(self):
        _make_banner(query_pattern="shoes", is_active=False)
        result = get_banners_for_query("products", "shoes")
        assert result == []

    @pytest.mark.django_db
    def test_tenant_specific_banner_matches(self):
        banner = _make_banner(query_pattern="shoes", tenant_id="acme")
        result = get_banners_for_query("products", "shoes", tenant_id="acme")
        assert len(result) == 1
        assert result[0].pk == banner.pk

    @pytest.mark.django_db
    def test_different_tenant_does_not_match(self):
        _make_banner(query_pattern="shoes", tenant_id="acme")
        result = get_banners_for_query("products", "shoes", tenant_id="other")
        assert result == []

    @pytest.mark.django_db
    def test_hit_count_incremented_on_match(self):
        banner = _make_banner(query_pattern="shoes", hit_count=0)
        get_banners_for_query("products", "shoes")
        banner.refresh_from_db()
        assert banner.hit_count == 1
