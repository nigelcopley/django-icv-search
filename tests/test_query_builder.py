"""Tests for the SearchQuery fluent query builder DSL."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from icv_search.backends import reset_search_backend
from icv_search.backends.dummy import DummyBackend
from icv_search.pagination import ICVSearchPaginator
from icv_search.query import SearchQuery, _build_filter_expression, _format_value
from icv_search.services import create_index, index_documents
from icv_search.types import SearchResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def use_dummy_backend(settings):
    """Use DummyBackend and reset state between tests."""
    settings.ICV_SEARCH_BACKEND = "icv_search.backends.dummy.DummyBackend"
    settings.ICV_SEARCH_AUTO_SYNC = False
    settings.ICV_SEARCH_LOG_QUERIES = False
    reset_search_backend()
    DummyBackend.reset()
    yield
    DummyBackend.reset()
    reset_search_backend()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestSearchQueryConstruction:
    """SearchQuery initialises with sensible defaults."""

    def test_accepts_string_index_name(self):
        q = SearchQuery("products")
        assert q._index == "products"

    def test_default_query_is_empty_string(self):
        q = SearchQuery("products")
        assert q._query == ""

    def test_default_filters_empty(self):
        q = SearchQuery("products")
        assert q._filters == {}

    def test_default_sort_empty(self):
        q = SearchQuery("products")
        assert q._sort == []

    def test_default_facets_empty(self):
        q = SearchQuery("products")
        assert q._facets == []

    def test_default_tenant_empty(self):
        q = SearchQuery("products")
        assert q._tenant == ""

    def test_default_limit_none(self):
        q = SearchQuery("products")
        assert q._limit is None

    def test_default_offset_none(self):
        q = SearchQuery("products")
        assert q._offset is None


# ---------------------------------------------------------------------------
# Fluent interface — all methods return self
# ---------------------------------------------------------------------------


class TestFluentInterface:
    """Every builder method must return the same SearchQuery instance."""

    def test_text_returns_self(self):
        q = SearchQuery("products")
        assert q.text("shoes") is q

    def test_filter_returns_self(self):
        q = SearchQuery("products")
        assert q.filter(brand="Nike") is q

    def test_sort_returns_self(self):
        q = SearchQuery("products")
        assert q.sort("price") is q

    def test_facets_returns_self(self):
        q = SearchQuery("products")
        assert q.facets("brand") is q

    def test_highlight_returns_self(self):
        q = SearchQuery("products")
        assert q.highlight("name") is q

    def test_geo_near_returns_self(self):
        q = SearchQuery("products")
        assert q.geo_near(lat=51.5, lng=-0.12) is q

    def test_limit_returns_self(self):
        q = SearchQuery("products")
        assert q.limit(20) is q

    def test_offset_returns_self(self):
        q = SearchQuery("products")
        assert q.offset(0) is q

    def test_with_ranking_scores_returns_self(self):
        q = SearchQuery("products")
        assert q.with_ranking_scores() is q

    def test_matching_strategy_returns_self(self):
        q = SearchQuery("products")
        assert q.matching_strategy("all") is q

    def test_tenant_returns_self(self):
        q = SearchQuery("products")
        assert q.tenant("acme") is q

    def test_user_returns_self(self):
        q = SearchQuery("products")
        assert q.user(None) is q

    def test_metadata_returns_self(self):
        q = SearchQuery("products")
        assert q.metadata({"page": "home"}) is q


# ---------------------------------------------------------------------------
# Method state
# ---------------------------------------------------------------------------


class TestMethodState:
    """Builder methods store their arguments correctly."""

    def test_text_sets_query(self):
        q = SearchQuery("products").text("running shoes")
        assert q._query == "running shoes"

    def test_sort_sets_fields(self):
        q = SearchQuery("products").sort("-price", "name")
        assert q._sort == ["-price", "name"]

    def test_facets_sets_fields(self):
        q = SearchQuery("products").facets("brand", "category")
        assert q._facets == ["brand", "category"]

    def test_limit_sets_value(self):
        q = SearchQuery("products").limit(50)
        assert q._limit == 50

    def test_offset_sets_value(self):
        q = SearchQuery("products").offset(40)
        assert q._offset == 40

    def test_with_ranking_scores_sets_flag(self):
        q = SearchQuery("products").with_ranking_scores()
        assert q._with_ranking_scores is True

    def test_matching_strategy_sets_value(self):
        q = SearchQuery("products").matching_strategy("frequency")
        assert q._matching_strategy == "frequency"

    def test_tenant_sets_id(self):
        q = SearchQuery("products").tenant("acme")
        assert q._tenant == "acme"

    def test_user_sets_user(self):
        mock_user = MagicMock()
        q = SearchQuery("products").user(mock_user)
        assert q._user is mock_user

    def test_metadata_sets_dict(self):
        q = SearchQuery("products").metadata({"page": "home"})
        assert q._metadata == {"page": "home"}

    def test_highlight_sets_fields(self):
        q = SearchQuery("products").highlight("name", "description")
        assert q._highlight["fields"] == ["name", "description"]

    def test_highlight_sets_pre_tag(self):
        q = SearchQuery("products").highlight("name", pre_tag="<em>", post_tag="</em>")
        assert q._highlight["pre_tag"] == "<em>"
        assert q._highlight["post_tag"] == "</em>"

    def test_highlight_omits_tags_when_none(self):
        q = SearchQuery("products").highlight("name")
        assert "pre_tag" not in q._highlight
        assert "post_tag" not in q._highlight


# ---------------------------------------------------------------------------
# filter() merging
# ---------------------------------------------------------------------------


class TestFilterMerging:
    """Multiple .filter() calls must merge, with later calls winning on duplicate keys."""

    def test_single_filter_call(self):
        q = SearchQuery("products").filter(brand="Nike")
        assert q._filters == {"brand": "Nike"}

    def test_two_filter_calls_merge(self):
        q = SearchQuery("products").filter(brand="Nike").filter(colour="red")
        assert q._filters == {"brand": "Nike", "colour": "red"}

    def test_later_call_overrides_duplicate_key(self):
        q = SearchQuery("products").filter(brand="Nike").filter(brand="Adidas")
        assert q._filters == {"brand": "Adidas"}

    def test_lookup_suffixes_stored_as_given(self):
        q = SearchQuery("products").filter(price__gte=50, price__lte=200)
        assert q._filters["price__gte"] == 50
        assert q._filters["price__lte"] == 200


# ---------------------------------------------------------------------------
# geo_near
# ---------------------------------------------------------------------------


class TestGeoNear:
    """geo_near stores latitude, longitude and optional radius/sort."""

    def test_stores_lat_lng(self):
        q = SearchQuery("products").geo_near(lat=51.5, lng=-0.12)
        assert q._geo["lat"] == 51.5
        assert q._geo["lng"] == -0.12

    def test_stores_radius_when_given(self):
        q = SearchQuery("products").geo_near(lat=51.5, lng=-0.12, radius=5000)
        assert q._geo["radius"] == 5000

    def test_omits_radius_when_none(self):
        q = SearchQuery("products").geo_near(lat=51.5, lng=-0.12)
        assert "radius" not in q._geo

    def test_default_sort_is_asc(self):
        q = SearchQuery("products").geo_near(lat=51.5, lng=-0.12)
        assert q._geo["sort"] == "asc"

    def test_custom_sort_stored(self):
        q = SearchQuery("products").geo_near(lat=51.5, lng=-0.12, sort="desc")
        assert q._geo["sort"] == "desc"


# ---------------------------------------------------------------------------
# _build_params
# ---------------------------------------------------------------------------


class TestBuildParams:
    """_build_params() assembles the correct kwargs dict for search()."""

    def test_empty_builder_produces_empty_params(self):
        params = SearchQuery("products")._build_params()
        assert params == {}

    def test_filter_included(self):
        params = SearchQuery("products").filter(brand="Nike")._build_params()
        assert "filter" in params

    def test_sort_included(self):
        params = SearchQuery("products").sort("price")._build_params()
        assert params["sort"] == ["price"]

    def test_facets_included(self):
        params = SearchQuery("products").facets("brand")._build_params()
        assert params["facets"] == ["brand"]

    def test_limit_included(self):
        params = SearchQuery("products").limit(25)._build_params()
        assert params["limit"] == 25

    def test_offset_included(self):
        params = SearchQuery("products").offset(50)._build_params()
        assert params["offset"] == 50

    def test_ranking_scores_included(self):
        params = SearchQuery("products").with_ranking_scores()._build_params()
        assert params["show_ranking_score"] is True

    def test_matching_strategy_included(self):
        params = SearchQuery("products").matching_strategy("all")._build_params()
        assert params["matching_strategy"] == "all"

    def test_geo_included(self):
        params = SearchQuery("products").geo_near(lat=51.5, lng=-0.12)._build_params()
        assert params["geo_point"] == (51.5, -0.12)
        assert params["geo_sort"] == "asc"

    def test_geo_with_radius_included(self):
        params = SearchQuery("products").geo_near(lat=51.5, lng=-0.12, radius=5000)._build_params()
        assert params["geo_point"] == (51.5, -0.12)
        assert params["geo_radius"] == 5000

    def test_geo_bbox_included(self):
        params = SearchQuery("products").geo_bbox(top_right=(52.0, 0.5), bottom_left=(51.0, -0.5))._build_params()
        assert params["geo_bbox"] == ((52.0, 0.5), (51.0, -0.5))

    def test_geo_polygon_included(self):
        vertices = [(51.5, -0.12), (52.0, 0.5), (51.0, 0.5)]
        params = SearchQuery("products").geo_polygon(vertices)._build_params()
        assert params["geo_polygon"] == vertices

    def test_highlight_fields_included(self):
        params = SearchQuery("products").highlight("name")._build_params()
        assert params["highlight_fields"] == ["name"]

    def test_highlight_tags_included(self):
        params = SearchQuery("products").highlight("name", pre_tag="<b>", post_tag="</b>")._build_params()
        assert params["highlight_pre_tag"] == "<b>"
        assert params["highlight_post_tag"] == "</b>"


# ---------------------------------------------------------------------------
# .execute()
# ---------------------------------------------------------------------------


class TestExecute:
    """execute() calls the search service and returns a SearchResult."""

    @pytest.mark.django_db
    def test_returns_search_result(self):
        create_index("products")
        result = SearchQuery("products").text("hello").execute()
        assert isinstance(result, SearchResult)

    @pytest.mark.django_db
    def test_passes_query_to_backend(self):
        index = create_index("products")
        index_documents(index, [{"id": "1", "title": "Running shoes"}])
        result = SearchQuery("products").text("Running").execute()
        assert len(result.hits) == 1

    @pytest.mark.django_db
    def test_passes_limit_to_backend(self):
        index = create_index("products")
        index_documents(index, [{"id": str(i)} for i in range(10)])
        result = SearchQuery("products").text("").limit(3).execute()
        assert len(result.hits) == 3

    @pytest.mark.django_db
    def test_passes_sort_to_backend(self):
        """Sort param is forwarded — backend receives it without error."""
        create_index("products")
        result = SearchQuery("products").sort("name").execute()
        assert isinstance(result, SearchResult)

    @pytest.mark.django_db
    def test_passes_tenant_to_search(self):
        from icv_search.services import create_index as ci

        ci("products", tenant_id="acme")
        result = SearchQuery("products").tenant("acme").text("").execute()
        assert isinstance(result, SearchResult)

    @pytest.mark.django_db
    def test_passes_user_to_search_service(self, settings):
        from icv_search.models.analytics import SearchQueryLog

        settings.ICV_SEARCH_LOG_QUERIES = True
        create_index("products")

        with patch("icv_search.services.search._is_saved_user", return_value=False):
            SearchQuery("products").text("hello").user(None).execute()

        log = SearchQueryLog.objects.get()
        assert log.user_id is None

    @pytest.mark.django_db
    def test_passes_metadata_to_search_service(self, settings):
        from icv_search.models.analytics import SearchQueryLog

        settings.ICV_SEARCH_LOG_QUERIES = True
        create_index("products")
        SearchQuery("products").text("hello").metadata({"page": "shop"}).execute()

        log = SearchQueryLog.objects.get()
        assert log.metadata == {"page": "shop"}


# ---------------------------------------------------------------------------
# .paginate()
# ---------------------------------------------------------------------------


class TestPaginate:
    """paginate() returns an ICVSearchPaginator with the correct per_page."""

    @pytest.mark.django_db
    def test_returns_icvsearch_paginator(self):
        create_index("products")
        paginator = SearchQuery("products").text("").paginate(per_page=10)
        assert isinstance(paginator, ICVSearchPaginator)

    @pytest.mark.django_db
    def test_per_page_sets_limit(self):
        create_index("products")
        paginator = SearchQuery("products").text("").paginate(per_page=15)
        assert paginator.per_page == 15

    @pytest.mark.django_db
    def test_default_per_page_is_20(self):
        create_index("products")
        paginator = SearchQuery("products").text("").paginate()
        assert paginator.per_page == 20


# ---------------------------------------------------------------------------
# _build_filter_expression helper
# ---------------------------------------------------------------------------


class TestBuildFilterExpression:
    """Unit tests for the private filter expression builder."""

    def test_equality_filter_string(self):
        exprs = _build_filter_expression({"brand": "Nike"})
        assert exprs == ['brand = "Nike"']

    def test_equality_filter_integer(self):
        exprs = _build_filter_expression({"stock": 5})
        assert exprs == ["stock = 5"]

    def test_equality_filter_boolean_true(self):
        exprs = _build_filter_expression({"is_active": True})
        assert exprs == ["is_active = true"]

    def test_equality_filter_boolean_false(self):
        exprs = _build_filter_expression({"is_active": False})
        assert exprs == ["is_active = false"]

    def test_gte_operator(self):
        exprs = _build_filter_expression({"price__gte": 50})
        assert exprs == ["price >= 50"]

    def test_lte_operator(self):
        exprs = _build_filter_expression({"price__lte": 200})
        assert exprs == ["price <= 200"]

    def test_gt_operator(self):
        exprs = _build_filter_expression({"rating__gt": 4})
        assert exprs == ["rating > 4"]

    def test_lt_operator(self):
        exprs = _build_filter_expression({"rating__lt": 3})
        assert exprs == ["rating < 3"]

    def test_ne_operator(self):
        exprs = _build_filter_expression({"status__ne": "inactive"})
        assert exprs == ['status != "inactive"']

    def test_in_operator(self):
        exprs = _build_filter_expression({"category__in": ["shoes", "boots"]})
        assert exprs == ['category IN ["shoes", "boots"]']

    def test_multiple_filters_produce_multiple_expressions(self):
        exprs = _build_filter_expression({"brand": "Nike", "price__gte": 50})
        assert len(exprs) == 2

    def test_string_value_escapes_double_quotes(self):
        exprs = _build_filter_expression({"name": 'He said "hello"'})
        assert '\\"' in exprs[0]


# ---------------------------------------------------------------------------
# _format_value helper
# ---------------------------------------------------------------------------


class TestFormatValue:
    """Unit tests for the private value formatter."""

    def test_string_wrapped_in_double_quotes(self):
        assert _format_value("Nike") == '"Nike"'

    def test_integer_as_string(self):
        assert _format_value(42) == "42"

    def test_float_as_string(self):
        assert _format_value(3.14) == "3.14"

    def test_true_as_lowercase(self):
        assert _format_value(True) == "true"

    def test_false_as_lowercase(self):
        assert _format_value(False) == "false"


# ---------------------------------------------------------------------------
# Top-level export
# ---------------------------------------------------------------------------


def test_search_query_exported_from_top_level():
    """SearchQuery must be importable from the package root."""
    import icv_search

    assert icv_search.SearchQuery is SearchQuery
