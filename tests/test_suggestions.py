"""Tests for the search suggestion service functions."""

from __future__ import annotations

import datetime

import pytest

from icv_search.services.suggestions import get_suggested_queries, get_trending_searches
from icv_search.testing.factories import SearchQueryAggregateFactory


def _today() -> datetime.date:
    return datetime.date.today()


def _days_ago(n: int) -> datetime.date:
    return _today() - datetime.timedelta(days=n)


class TestGetTrendingSearches:
    """get_trending_searches() — query trend ranking from aggregate data."""

    @pytest.mark.django_db
    def test_returns_queries_ordered_by_count(self):
        SearchQueryAggregateFactory(index_name="products", query="shoes", total_count=50, date=_today())
        SearchQueryAggregateFactory(index_name="products", query="boots", total_count=20, date=_today())
        result = get_trending_searches("products")
        assert result[0]["query"] == "shoes"
        assert result[1]["query"] == "boots"

    @pytest.mark.django_db
    def test_days_filter_excludes_old_records(self):
        SearchQueryAggregateFactory(index_name="products", query="old", total_count=100, date=_days_ago(10))
        SearchQueryAggregateFactory(index_name="products", query="recent", total_count=5, date=_today())
        result = get_trending_searches("products", days=3)
        assert len(result) == 1
        assert result[0]["query"] == "recent"

    @pytest.mark.django_db
    def test_empty_when_no_data(self):
        result = get_trending_searches("products")
        assert result == []

    @pytest.mark.django_db
    def test_respects_limit(self):
        for i in range(10):
            SearchQueryAggregateFactory(index_name="products", query=f"query_{i}", total_count=i + 1, date=_today())
        result = get_trending_searches("products", limit=3)
        assert len(result) == 3

    @pytest.mark.django_db
    def test_tenant_scoping(self):
        SearchQueryAggregateFactory(
            index_name="products", query="shoes", total_count=30, tenant_id="acme", date=_today()
        )
        SearchQueryAggregateFactory(
            index_name="products", query="shoes", total_count=10, tenant_id="beta", date=_today()
        )
        result = get_trending_searches("products", tenant_id="acme")
        assert len(result) == 1
        assert result[0]["count"] == 30

    @pytest.mark.django_db
    def test_aggregates_count_across_days_within_window(self):
        # Two rows for the same query on different days, both within window.
        SearchQueryAggregateFactory(index_name="products", query="shoes", total_count=10, date=_today())
        SearchQueryAggregateFactory(index_name="products", query="shoes", total_count=5, date=_days_ago(1))
        result = get_trending_searches("products", days=7)
        assert result[0]["query"] == "shoes"
        assert result[0]["count"] == 15

    @pytest.mark.django_db
    def test_scopes_to_index_name(self):
        SearchQueryAggregateFactory(index_name="products", query="shoes", total_count=20, date=_today())
        SearchQueryAggregateFactory(index_name="articles", query="shoes", total_count=100, date=_today())
        result = get_trending_searches("products")
        assert len(result) == 1
        assert result[0]["count"] == 20


class TestGetSuggestedQueries:
    """get_suggested_queries() — typeahead prefix matching from aggregate data."""

    @pytest.mark.django_db
    def test_returns_prefix_matches(self):
        SearchQueryAggregateFactory(index_name="products", query="running shoes", total_count=10, date=_today())
        SearchQueryAggregateFactory(index_name="products", query="running boots", total_count=5, date=_today())
        result = get_suggested_queries("products", "run")
        queries = [r["query"] for r in result]
        assert "running shoes" in queries
        assert "running boots" in queries

    @pytest.mark.django_db
    def test_empty_partial_returns_empty_list(self):
        SearchQueryAggregateFactory(index_name="products", query="shoes", total_count=10, date=_today())
        result = get_suggested_queries("products", "")
        assert result == []

    @pytest.mark.django_db
    def test_whitespace_only_partial_returns_empty_list(self):
        result = get_suggested_queries("products", "   ")
        assert result == []

    @pytest.mark.django_db
    def test_respects_limit(self):
        for i in range(10):
            SearchQueryAggregateFactory(
                index_name="products",
                query=f"shoe_{i}",
                total_count=i + 1,
                date=_today(),
            )
        result = get_suggested_queries("products", "shoe", limit=3)
        assert len(result) == 3

    @pytest.mark.django_db
    def test_tenant_scoping(self):
        SearchQueryAggregateFactory(
            index_name="products", query="shoes", total_count=20, tenant_id="acme", date=_today()
        )
        SearchQueryAggregateFactory(
            index_name="products", query="shoes", total_count=5, tenant_id="beta", date=_today()
        )
        result = get_suggested_queries("products", "shoe", tenant_id="acme")
        assert len(result) == 1
        assert result[0]["count"] == 20

    @pytest.mark.django_db
    def test_only_considers_last_30_days(self):
        SearchQueryAggregateFactory(index_name="products", query="shoes", total_count=10, date=_days_ago(31))
        SearchQueryAggregateFactory(index_name="products", query="shoes", total_count=5, date=_today())
        result = get_suggested_queries("products", "shoe")
        # Only the row within 30 days is included.
        assert len(result) == 1
        assert result[0]["count"] == 5

    @pytest.mark.django_db
    def test_normalises_partial_to_lowercase(self):
        SearchQueryAggregateFactory(index_name="products", query="running shoes", total_count=10, date=_today())
        # Uppercase partial should still match the lowercase stored query.
        result = get_suggested_queries("products", "RUNNING")
        assert len(result) == 1
        assert result[0]["query"] == "running shoes"

    @pytest.mark.django_db
    def test_ordered_by_count_descending(self):
        SearchQueryAggregateFactory(index_name="products", query="shoe rack", total_count=5, date=_today())
        SearchQueryAggregateFactory(index_name="products", query="shoes", total_count=30, date=_today())
        result = get_suggested_queries("products", "shoe")
        assert result[0]["query"] == "shoes"

    @pytest.mark.django_db
    def test_no_match_returns_empty_list(self):
        SearchQueryAggregateFactory(index_name="products", query="boots", total_count=10, date=_today())
        result = get_suggested_queries("products", "shoe")
        assert result == []
