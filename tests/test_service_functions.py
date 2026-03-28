"""Tests for the new service functions added to icv-search.

Covers: get_task, get_index_settings, multi_search, synonym management,
and stop-word management.
"""

from __future__ import annotations

import pytest

from icv_search.backends import reset_search_backend
from icv_search.backends.dummy import DummyBackend
from icv_search.services import (
    SearchResult,
    TaskResult,
    create_index,
    get_index_settings,
    get_stop_words,
    get_synonyms,
    get_task,
    index_documents,
    multi_search,
    reset_stop_words,
    reset_synonyms,
    update_index_settings,
    update_stop_words,
    update_synonyms,
)


@pytest.fixture(autouse=True)
def use_dummy_backend(settings):
    """Use DummyBackend for all tests in this module."""
    settings.ICV_SEARCH_BACKEND = "icv_search.backends.dummy.DummyBackend"
    settings.ICV_SEARCH_AUTO_SYNC = False
    reset_search_backend()
    DummyBackend.reset()
    yield
    DummyBackend.reset()
    reset_search_backend()


# ---------------------------------------------------------------------------
# get_task
# ---------------------------------------------------------------------------


class TestGetTask:
    """get_task() service function."""

    def test_returns_task_result_instance(self):
        result = get_task("some-task-uid")
        assert isinstance(result, TaskResult)

    def test_task_uid_is_preserved(self):
        result = get_task("abc-123")
        assert result.task_uid == "abc-123"

    def test_dummy_backend_always_returns_succeeded(self):
        result = get_task("any-uid")
        assert result.status == "succeeded"

    def test_raw_field_is_populated(self):
        result = get_task("task-1")
        assert isinstance(result.raw, dict)
        assert "uid" in result.raw


# ---------------------------------------------------------------------------
# get_index_settings
# ---------------------------------------------------------------------------


class TestGetIndexSettings:
    """get_index_settings() service function."""

    @pytest.mark.django_db
    def test_returns_dict(self):
        index = create_index("products")
        result = get_index_settings(index)
        assert isinstance(result, dict)

    @pytest.mark.django_db
    def test_returns_empty_dict_for_fresh_index(self):
        index = create_index("products")
        result = get_index_settings(index)
        assert result == {}

    @pytest.mark.django_db
    def test_returns_settings_pushed_to_engine(self):
        index = create_index("products")
        update_index_settings(index, {"searchableAttributes": ["name", "description"]})
        result = get_index_settings(index)
        assert result.get("searchableAttributes") == ["name", "description"]

    @pytest.mark.django_db
    def test_resolves_index_by_name(self):
        create_index("articles")
        update_index_settings("articles", {"filterableAttributes": ["category"]})
        result = get_index_settings("articles")
        assert result.get("filterableAttributes") == ["category"]

    @pytest.mark.django_db
    def test_reflects_latest_engine_state(self):
        """Each call fetches live state — not a stale cached value."""
        index = create_index("products")
        update_index_settings(index, {"searchableAttributes": ["name"]})
        update_index_settings(index, {"sortableAttributes": ["price"]})
        result = get_index_settings(index)
        # The engine stores whatever was last pushed; both attributes must be present
        # because update_index_settings merges into index.settings before pushing.
        assert "searchableAttributes" in result
        assert "sortableAttributes" in result

    @pytest.mark.django_db
    def test_resolves_index_by_name_with_tenant(self):
        create_index("products", tenant_id="acme")
        update_index_settings("products", {"searchableAttributes": ["sku"]}, "acme")
        result = get_index_settings("products", tenant_id="acme")
        assert result.get("searchableAttributes") == ["sku"]


# ---------------------------------------------------------------------------
# multi_search
# ---------------------------------------------------------------------------


class TestMultiSearch:
    """multi_search() service function."""

    @pytest.mark.django_db
    def test_returns_list_of_search_results(self):
        create_index("articles")
        results = multi_search([{"index_name": "articles", "query": ""}])
        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)

    @pytest.mark.django_db
    def test_multiple_queries_return_independent_results(self):
        articles = create_index("articles")
        products = create_index("products")
        index_documents(articles, [{"id": "1", "title": "Django guide"}])
        index_documents(products, [{"id": "p1", "name": "Widget"}, {"id": "p2", "name": "Gadget"}])

        results = multi_search(
            [
                {"index_name": "articles", "query": "Django"},
                {"index_name": "products", "query": ""},
            ]
        )

        assert len(results) == 2
        # First query matched one article
        assert len(results[0].hits) == 1
        assert results[0].hits[0]["title"] == "Django guide"
        # Second query returned all products
        assert len(results[1].hits) == 2

    @pytest.mark.django_db
    def test_empty_query_returns_all_documents(self):
        index = create_index("items")
        index_documents(index, [{"id": str(i)} for i in range(5)])
        results = multi_search([{"index_name": "items", "query": ""}])
        assert results[0].estimated_total_hits == 5

    @pytest.mark.django_db
    def test_limit_param_is_respected(self):
        index = create_index("items")
        index_documents(index, [{"id": str(i), "name": f"Item {i}"} for i in range(10)])
        results = multi_search([{"index_name": "items", "query": "", "limit": 3}])
        assert len(results[0].hits) == 3

    @pytest.mark.django_db
    def test_single_query_returns_single_result(self):
        create_index("notes")
        index_documents("notes", [{"id": "1", "body": "hello world"}])
        results = multi_search([{"index_name": "notes", "query": "hello"}])
        assert len(results) == 1
        assert results[0].hits[0]["id"] == "1"

    @pytest.mark.django_db
    def test_result_order_matches_query_order(self):
        """Results must appear in the same order as input queries."""
        idx_a = create_index("alpha")
        idx_b = create_index("beta")
        idx_c = create_index("gamma")
        index_documents(idx_a, [{"id": "a1", "title": "Alpha doc"}])
        index_documents(idx_b, [{"id": "b1", "title": "Beta doc"}])
        index_documents(idx_c, [{"id": "c1", "title": "Gamma doc"}])

        results = multi_search(
            [
                {"index_name": "gamma", "query": "Gamma"},
                {"index_name": "alpha", "query": "Alpha"},
                {"index_name": "beta", "query": "Beta"},
            ]
        )

        assert results[0].hits[0]["title"] == "Gamma doc"
        assert results[1].hits[0]["title"] == "Alpha doc"
        assert results[2].hits[0]["title"] == "Beta doc"

    @pytest.mark.django_db
    def test_per_query_tenant_id_overrides_default(self):
        """A 'tenant_id' key in a query dict overrides the function-level tenant_id."""
        create_index("products", tenant_id="acme")
        results = multi_search(
            [{"index_name": "products", "query": "", "tenant_id": "acme"}],
            tenant_id="",
        )
        assert len(results) == 1

    @pytest.mark.django_db
    def test_function_level_tenant_id_is_used_when_not_overridden(self):
        create_index("products", tenant_id="acme")
        results = multi_search(
            [{"index_name": "products", "query": ""}],
            tenant_id="acme",
        )
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Synonym management
# ---------------------------------------------------------------------------


class TestGetSynonyms:
    """get_synonyms() service function."""

    @pytest.mark.django_db
    def test_returns_empty_dict_for_fresh_index(self):
        index = create_index("products")
        result = get_synonyms(index)
        assert result == {}

    @pytest.mark.django_db
    def test_returns_synonyms_after_update(self):
        index = create_index("products")
        update_index_settings(index, {"synonyms": {"phone": ["mobile", "handset"]}})
        result = get_synonyms(index)
        assert result == {"phone": ["mobile", "handset"]}

    @pytest.mark.django_db
    def test_resolves_index_by_name(self):
        create_index("articles")
        update_index_settings("articles", {"synonyms": {"doc": ["document"]}})
        result = get_synonyms("articles")
        assert result == {"doc": ["document"]}


class TestUpdateSynonyms:
    """update_synonyms() service function."""

    @pytest.mark.django_db
    def test_sets_synonyms_on_fresh_index(self):
        index = create_index("products")
        update_synonyms(index, {"phone": ["mobile", "handset"]})
        result = get_synonyms(index)
        assert result == {"phone": ["mobile", "handset"]}

    @pytest.mark.django_db
    def test_merges_with_existing_synonyms(self):
        index = create_index("products")
        update_synonyms(index, {"phone": ["mobile"]})
        update_synonyms(index, {"laptop": ["notebook"]})
        result = get_synonyms(index)
        assert "phone" in result
        assert "laptop" in result

    @pytest.mark.django_db
    def test_caller_value_wins_on_key_collision(self):
        index = create_index("products")
        update_synonyms(index, {"phone": ["mobile"]})
        update_synonyms(index, {"phone": ["handset", "cellular"]})
        result = get_synonyms(index)
        assert result["phone"] == ["handset", "cellular"]

    @pytest.mark.django_db
    def test_returns_search_index_instance(self):
        index = create_index("products")
        returned = update_synonyms(index, {"a": ["b"]})
        from icv_search.models import SearchIndex

        assert isinstance(returned, SearchIndex)

    @pytest.mark.django_db
    def test_resolves_index_by_name(self):
        create_index("articles")
        update_synonyms("articles", {"doc": ["document"]})
        result = get_synonyms("articles")
        assert result == {"doc": ["document"]}

    @pytest.mark.django_db
    def test_synonyms_persisted_to_engine(self):
        """Synonyms pushed to engine are visible via get_index_settings."""
        index = create_index("products")
        update_synonyms(index, {"phone": ["mobile"]})
        settings = get_index_settings(index)
        assert settings.get("synonyms", {}).get("phone") == ["mobile"]


class TestResetSynonyms:
    """reset_synonyms() service function."""

    @pytest.mark.django_db
    def test_clears_all_synonyms(self):
        index = create_index("products")
        update_synonyms(index, {"phone": ["mobile"], "laptop": ["notebook"]})
        reset_synonyms(index)
        result = get_synonyms(index)
        assert result == {}

    @pytest.mark.django_db
    def test_returns_search_index_instance(self):
        index = create_index("products")
        returned = reset_synonyms(index)
        from icv_search.models import SearchIndex

        assert isinstance(returned, SearchIndex)

    @pytest.mark.django_db
    def test_reset_on_fresh_index_is_idempotent(self):
        index = create_index("products")
        reset_synonyms(index)
        result = get_synonyms(index)
        assert result == {}

    @pytest.mark.django_db
    def test_resolves_index_by_name(self):
        create_index("articles")
        update_synonyms("articles", {"doc": ["document"]})
        reset_synonyms("articles")
        result = get_synonyms("articles")
        assert result == {}


# ---------------------------------------------------------------------------
# Stop-word management
# ---------------------------------------------------------------------------


class TestGetStopWords:
    """get_stop_words() service function."""

    @pytest.mark.django_db
    def test_returns_empty_list_for_fresh_index(self):
        index = create_index("products")
        result = get_stop_words(index)
        assert result == []

    @pytest.mark.django_db
    def test_returns_stop_words_after_update(self):
        index = create_index("products")
        update_index_settings(index, {"stopWords": ["the", "a", "an"]})
        result = get_stop_words(index)
        assert result == ["the", "a", "an"]

    @pytest.mark.django_db
    def test_resolves_index_by_name(self):
        create_index("articles")
        update_index_settings("articles", {"stopWords": ["is", "are"]})
        result = get_stop_words("articles")
        assert result == ["is", "are"]


class TestUpdateStopWords:
    """update_stop_words() service function."""

    @pytest.mark.django_db
    def test_sets_stop_words_on_fresh_index(self):
        index = create_index("products")
        update_stop_words(index, ["the", "a"])
        result = get_stop_words(index)
        assert result == ["the", "a"]

    @pytest.mark.django_db
    def test_replaces_existing_stop_words_entirely(self):
        """update_stop_words replaces — it does not merge."""
        index = create_index("products")
        update_stop_words(index, ["the", "a"])
        update_stop_words(index, ["is", "are"])
        result = get_stop_words(index)
        assert result == ["is", "are"]
        assert "the" not in result

    @pytest.mark.django_db
    def test_returns_search_index_instance(self):
        index = create_index("products")
        returned = update_stop_words(index, ["the"])
        from icv_search.models import SearchIndex

        assert isinstance(returned, SearchIndex)

    @pytest.mark.django_db
    def test_resolves_index_by_name(self):
        create_index("articles")
        update_stop_words("articles", ["and", "or"])
        result = get_stop_words("articles")
        assert result == ["and", "or"]

    @pytest.mark.django_db
    def test_stop_words_persisted_to_engine(self):
        """Stop words pushed to engine are visible via get_index_settings."""
        index = create_index("products")
        update_stop_words(index, ["the", "a"])
        settings = get_index_settings(index)
        assert settings.get("stopWords") == ["the", "a"]


class TestResetStopWords:
    """reset_stop_words() service function."""

    @pytest.mark.django_db
    def test_clears_all_stop_words(self):
        index = create_index("products")
        update_stop_words(index, ["the", "a", "an"])
        reset_stop_words(index)
        result = get_stop_words(index)
        assert result == []

    @pytest.mark.django_db
    def test_returns_search_index_instance(self):
        index = create_index("products")
        returned = reset_stop_words(index)
        from icv_search.models import SearchIndex

        assert isinstance(returned, SearchIndex)

    @pytest.mark.django_db
    def test_reset_on_fresh_index_is_idempotent(self):
        index = create_index("products")
        reset_stop_words(index)
        result = get_stop_words(index)
        assert result == []

    @pytest.mark.django_db
    def test_resolves_index_by_name(self):
        create_index("articles")
        update_stop_words("articles", ["the"])
        reset_stop_words("articles")
        result = get_stop_words("articles")
        assert result == []
