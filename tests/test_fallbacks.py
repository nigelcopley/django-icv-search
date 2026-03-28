"""Tests for the zero-result fallback service functions."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from icv_search.backends import reset_search_backend
from icv_search.backends.dummy import DummyBackend
from icv_search.models.merchandising import ZeroResultFallback
from icv_search.services.fallbacks import execute_fallback, get_fallback_for_query
from icv_search.types import MerchandisedSearchResult


@pytest.fixture(autouse=True)
def use_dummy_backend(settings):
    """Use DummyBackend and reset state between tests.

    Also disables the merchandising rule cache so that DB rollbacks between
    tests are not masked by stale cached rule lists.
    """
    settings.ICV_SEARCH_BACKEND = "icv_search.backends.dummy.DummyBackend"
    settings.ICV_SEARCH_AUTO_SYNC = False
    settings.ICV_SEARCH_LOG_QUERIES = False
    settings.ICV_SEARCH_MERCHANDISING_CACHE_TIMEOUT = 0
    reset_search_backend()
    DummyBackend.reset()
    yield
    DummyBackend.reset()
    reset_search_backend()


def _make_fallback(**kwargs) -> ZeroResultFallback:
    """Create and save a ZeroResultFallback with sensible defaults."""
    defaults = {
        "index_name": "products",
        "tenant_id": "",
        "query_pattern": "xyzzy",
        "match_type": "exact",
        "fallback_type": "redirect",
        "fallback_value": "https://example.com/fallback/",
        "is_active": True,
        "priority": 0,
        "max_retries": 1,
    }
    defaults.update(kwargs)
    return ZeroResultFallback.objects.create(**defaults)


class TestGetFallbackForQuery:
    """get_fallback_for_query() — rule matching and selection."""

    @pytest.mark.django_db
    def test_returns_matching_fallback(self):
        fallback = _make_fallback(query_pattern="xyzzy", match_type="exact")
        result = get_fallback_for_query("products", "xyzzy")
        assert result is not None
        assert result.pk == fallback.pk

    @pytest.mark.django_db
    def test_returns_none_when_no_match(self):
        _make_fallback(query_pattern="xyzzy", match_type="exact")
        result = get_fallback_for_query("products", "shoes")
        assert result is None

    @pytest.mark.django_db
    def test_returns_none_when_no_rules_exist(self):
        result = get_fallback_for_query("products", "xyzzy")
        assert result is None

    @pytest.mark.django_db
    def test_inactive_fallback_is_skipped(self):
        _make_fallback(query_pattern="xyzzy", is_active=False)
        result = get_fallback_for_query("products", "xyzzy")
        assert result is None

    @pytest.mark.django_db
    def test_scheduled_fallback_future_start_is_skipped(self):
        _make_fallback(
            query_pattern="xyzzy",
            starts_at=timezone.now() + timedelta(hours=1),
        )
        result = get_fallback_for_query("products", "xyzzy")
        assert result is None

    @pytest.mark.django_db
    def test_scheduled_fallback_past_end_is_skipped(self):
        _make_fallback(
            query_pattern="xyzzy",
            ends_at=timezone.now() - timedelta(hours=1),
        )
        result = get_fallback_for_query("products", "xyzzy")
        assert result is None

    @pytest.mark.django_db
    def test_priority_ordering_highest_priority_wins(self):
        low = _make_fallback(
            query_pattern="xyzzy",
            priority=1,
            fallback_value="https://example.com/low/",
        )
        high = _make_fallback(
            query_pattern="xyzzy",
            priority=10,
            fallback_value="https://example.com/high/",
        )
        result = get_fallback_for_query("products", "xyzzy")
        assert result is not None
        assert result.pk == high.pk
        assert result.pk != low.pk

    @pytest.mark.django_db
    def test_tenant_scoping_matches_correct_tenant(self):
        fallback = _make_fallback(query_pattern="xyzzy", tenant_id="acme")
        result = get_fallback_for_query("products", "xyzzy", tenant_id="acme")
        assert result is not None
        assert result.pk == fallback.pk

    @pytest.mark.django_db
    def test_tenant_scoping_different_tenant_no_match(self):
        _make_fallback(query_pattern="xyzzy", tenant_id="acme")
        result = get_fallback_for_query("products", "xyzzy", tenant_id="other")
        assert result is None


class TestExecuteFallbackRedirect:
    """execute_fallback() with redirect type."""

    @pytest.mark.django_db
    def test_redirect_type_returns_url_string(self):
        fallback = _make_fallback(
            fallback_type="redirect",
            fallback_value="https://example.com/fallback/",
        )
        result = execute_fallback(fallback, "products", "xyzzy")
        assert result == "https://example.com/fallback/"

    @pytest.mark.django_db
    def test_redirect_result_is_a_string(self):
        fallback = _make_fallback(
            fallback_type="redirect",
            fallback_value="https://example.com/no-results/",
        )
        result = execute_fallback(fallback, "products", "xyzzy")
        assert isinstance(result, str)


class TestExecuteFallbackAlternativeQuery:
    """execute_fallback() with alternative_query type."""

    @pytest.mark.django_db
    def test_alternative_query_runs_search_and_returns_merchandised_result(self, settings):
        from icv_search.services import create_index, index_documents

        settings.ICV_SEARCH_LOG_QUERIES = False
        index = create_index("products")
        index_documents(index, [{"id": "1", "name": "Running Shoes"}])

        fallback = _make_fallback(
            fallback_type="alternative_query",
            fallback_value="running",
            max_retries=1,
        )
        result = execute_fallback(fallback, "products", "xyzzy")
        assert isinstance(result, MerchandisedSearchResult)

    @pytest.mark.django_db
    def test_alternative_query_is_fallback_true(self, settings):
        from icv_search.services import create_index, index_documents

        settings.ICV_SEARCH_LOG_QUERIES = False
        index = create_index("products")
        index_documents(index, [{"id": "1", "name": "Running Shoes"}])

        fallback = _make_fallback(
            fallback_type="alternative_query",
            fallback_value="running",
            max_retries=1,
        )
        result = execute_fallback(fallback, "products", "xyzzy")
        assert result.is_fallback is True

    @pytest.mark.django_db
    def test_alternative_query_preserves_original_query(self, settings):
        from icv_search.services import create_index, index_documents

        settings.ICV_SEARCH_LOG_QUERIES = False
        index = create_index("products")
        index_documents(index, [{"id": "1", "name": "Running Shoes"}])

        fallback = _make_fallback(
            fallback_type="alternative_query",
            fallback_value="running",
            max_retries=1,
        )
        result = execute_fallback(fallback, "products", "xyzzy")
        assert result.original_query == "xyzzy"

    @pytest.mark.django_db
    def test_alternative_query_retry_drops_words_on_zero_results(self, settings):
        from icv_search.services import create_index, index_documents

        settings.ICV_SEARCH_LOG_QUERIES = False
        index = create_index("products")
        # Only "shoes" matches — the full phrase "running shoes" will first
        # return zero results, then retry drops "shoes" → "running" also zero,
        # but we can verify the mechanism with a controlled fallback_value.
        index_documents(index, [{"id": "1", "name": "shoes"}])

        # "running shoes" → zero results → retry → "running" → still zero
        fallback = _make_fallback(
            fallback_type="alternative_query",
            fallback_value="running shoes",
            max_retries=3,
        )
        result = execute_fallback(fallback, "products", "xyzzy")
        # Retries are exhausted gracefully; is_fallback must still be True.
        assert isinstance(result, MerchandisedSearchResult)
        assert result.is_fallback is True

    @pytest.mark.django_db
    def test_alternative_query_max_retries_limits_attempts(self, monkeypatch):
        """max_retries=1 means one attempt total; max_retries=3 allows two retries."""
        import sys

        from icv_search.services import create_index
        from icv_search.types import SearchResult

        create_index("products")

        call_queries: list[str] = []

        def fake_search(name_or_index, query, tenant_id="", **params):
            call_queries.append(query)
            return SearchResult()  # always zero hits

        # execute_fallback does `from icv_search.services.search import search`
        # at call time. Patching the 'search' attribute on the already-imported
        # module object intercepts the name binding at import time.
        search_mod = sys.modules["icv_search.services.search"]  # noqa: PLC0415
        monkeypatch.setattr(search_mod, "search", fake_search)

        fallback = _make_fallback(
            fallback_type="alternative_query",
            fallback_value="word1 word2 word3",
            max_retries=1,
        )
        execute_fallback(fallback, "products", "xyzzy")
        # max_retries=1 → while condition (retries < 0) never true → 1 call only.
        assert len(call_queries) == 1

        # With max_retries=3 and a 3-word phrase, we expect the initial call
        # plus up to 2 retries (dropping "word3" then "word2").
        fallback.max_retries = 3
        call_queries.clear()
        execute_fallback(fallback, "products", "xyzzy")
        assert len(call_queries) == 3


class TestExecuteFallbackCuratedResults:
    """execute_fallback() with curated_results type."""

    @pytest.mark.django_db
    def test_curated_results_returns_merchandised_result(self, settings):
        from icv_search.services import create_index, index_documents

        settings.ICV_SEARCH_LOG_QUERIES = False
        index = create_index("products")
        index_documents(
            index,
            [
                {"id": "1", "name": "Product A"},
                {"id": "2", "name": "Product B"},
            ],
        )

        fallback = _make_fallback(
            fallback_type="curated_results",
            fallback_value="1, 2",
        )
        result = execute_fallback(fallback, "products", "xyzzy")
        assert isinstance(result, MerchandisedSearchResult)
        assert result.is_fallback is True
        assert result.original_query == "xyzzy"

    @pytest.mark.django_db
    def test_curated_results_empty_value_returns_empty_result(self, settings):
        from icv_search.services import create_index

        settings.ICV_SEARCH_LOG_QUERIES = False
        create_index("products")

        fallback = _make_fallback(
            fallback_type="curated_results",
            fallback_value="",
        )
        result = execute_fallback(fallback, "products", "xyzzy")
        assert isinstance(result, MerchandisedSearchResult)
        assert result.is_fallback is True


class TestExecuteFallbackPopularInCategory:
    """execute_fallback() with popular_in_category type."""

    @pytest.mark.django_db
    def test_popular_in_category_returns_merchandised_result(self, settings):
        from icv_search.services import create_index, index_documents

        settings.ICV_SEARCH_LOG_QUERIES = False
        index = create_index("products")
        index_documents(
            index,
            [
                {"id": "1", "name": "Trainer", "category": "footwear"},
                {"id": "2", "name": "Boot", "category": "footwear"},
            ],
        )

        fallback = _make_fallback(
            fallback_type="popular_in_category",
            fallback_value="footwear",
        )
        result = execute_fallback(fallback, "products", "xyzzy")
        assert isinstance(result, MerchandisedSearchResult)
        assert result.is_fallback is True
        assert result.original_query == "xyzzy"


class TestExecuteFallbackUnknownType:
    """execute_fallback() with an unknown fallback type."""

    @pytest.mark.django_db
    def test_unknown_type_returns_empty_merchandised_result(self):
        fallback = _make_fallback(
            fallback_type="redirect",  # valid DB choice
            fallback_value="",
        )
        # Manually override the type to something unknown without DB round-trip.
        fallback.fallback_type = "completely_unknown"
        result = execute_fallback(fallback, "products", "xyzzy")
        assert isinstance(result, MerchandisedSearchResult)
        assert result.is_fallback is True
        assert result.hits == []
