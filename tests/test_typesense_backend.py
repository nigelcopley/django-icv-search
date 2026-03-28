"""Tests for the Typesense backend.

All tests are skipped when ``typesense`` is not installed. SDK calls are
fully mocked — no live server is required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

try:
    import typesense  # noqa: F401

    HAS_TYPESENSE = True
except ImportError:
    HAS_TYPESENSE = False

pytestmark = pytest.mark.skipif(not HAS_TYPESENSE, reason="typesense not installed")

# ---------------------------------------------------------------------------
# Import the module under test only when typesense is available so that
# collection does not fail on machines without the SDK.
# ---------------------------------------------------------------------------
if HAS_TYPESENSE:
    from icv_search.backends.typesense import (
        TypesenseBackend,
        _build_schema_fields,
        translate_filter_to_typesense,
        translate_sort_to_typesense,
    )
    from icv_search.exceptions import IndexNotFoundError, SearchBackendError, SearchTimeoutError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_backend(**kwargs: Any) -> TypesenseBackend:
    """Construct a TypesenseBackend with a fully mocked typesense.Client."""
    with patch("icv_search.backends.typesense.typesense.Client") as mock_cls:
        mock_cls.return_value = MagicMock()
        backend = TypesenseBackend(
            url="http://localhost:8108",
            api_key="test-key",
            **kwargs,
        )
    # Replace the client with a fresh MagicMock for assertion access.
    backend._client = MagicMock()
    return backend


def _ts_search_response(
    hits: list[dict[str, Any]] | None = None,
    found: int = 0,
    search_time_ms: int = 3,
    facet_counts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal Typesense search response dict."""
    return {
        "found": found,
        "search_time_ms": search_time_ms,
        "hits": hits or [],
        "facet_counts": facet_counts or [],
    }


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_raises_improperly_configured_when_sdk_missing(self) -> None:
        """ImproperlyConfigured is raised when typesense is not installed."""
        with patch("icv_search.backends.typesense._HAS_TYPESENSE", False):
            from django.core.exceptions import ImproperlyConfigured

            with pytest.raises(ImproperlyConfigured, match="typesense is required"):
                TypesenseBackend(url="http://localhost:8108", api_key="key")

    def test_parses_http_url_into_node_config(self) -> None:
        """URL is parsed into host/port/protocol for the Typesense client."""
        with patch("icv_search.backends.typesense.typesense.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            TypesenseBackend(url="http://myhost:8108", api_key="my-key")

        # Client is always called positionally: Client({...})
        config = mock_cls.call_args[0][0]
        node = config["nodes"][0]
        assert node["host"] == "myhost"
        assert node["port"] == "8108"
        assert node["protocol"] == "http"

    def test_parses_https_url(self) -> None:
        """HTTPS URL results in protocol=https."""
        with patch("icv_search.backends.typesense.typesense.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            TypesenseBackend(url="https://cloud.typesense.io:443", api_key="key")

        config = mock_cls.call_args[0][0]
        node = config["nodes"][0]
        assert node["protocol"] == "https"

    def test_accepts_nodes_kwarg_for_ha_cluster(self) -> None:
        """Explicit nodes list bypasses URL parsing."""
        nodes = [
            {"host": "n1.example.com", "port": "443", "protocol": "https"},
            {"host": "n2.example.com", "port": "443", "protocol": "https"},
        ]
        with patch("icv_search.backends.typesense.typesense.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            TypesenseBackend(url="http://localhost:8108", api_key="key", nodes=nodes)

        config = mock_cls.call_args[0][0]
        assert config["nodes"] == nodes

    def test_api_key_forwarded_to_client(self) -> None:
        """api_key is passed directly to the Typesense client config."""
        with patch("icv_search.backends.typesense.typesense.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            TypesenseBackend(url="http://localhost:8108", api_key="secret-api-key")

        config = mock_cls.call_args[0][0]
        assert config["api_key"] == "secret-api-key"

    def test_connection_timeout_default_matches_timeout(self) -> None:
        """connection_timeout_seconds defaults to the timeout kwarg."""
        with patch("icv_search.backends.typesense.typesense.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            TypesenseBackend(url="http://localhost:8108", api_key="k", timeout=15)

        config = mock_cls.call_args[0][0]
        assert config["connection_timeout_seconds"] == 15


# ---------------------------------------------------------------------------
# Filter translation
# ---------------------------------------------------------------------------


class TestFilterTranslation:
    def test_scalar_string_equality(self) -> None:
        result = translate_filter_to_typesense({"city": "Madrid"})
        assert result == "city:=`Madrid`"

    def test_integer_equality(self) -> None:
        result = translate_filter_to_typesense({"category_id": 5})
        assert result == "category_id:=5"

    def test_boolean_true(self) -> None:
        result = translate_filter_to_typesense({"is_active": True})
        assert result == "is_active:=true"

    def test_boolean_false(self) -> None:
        result = translate_filter_to_typesense({"is_active": False})
        assert result == "is_active:=false"

    def test_list_value(self) -> None:
        result = translate_filter_to_typesense({"category": ["books", "games"]})
        assert result == "category:=[`books`,`games`]"

    def test_gte_range(self) -> None:
        result = translate_filter_to_typesense({"price__gte": 50})
        assert result == "price:>=50"

    def test_gt_range(self) -> None:
        result = translate_filter_to_typesense({"price__gt": 10})
        assert result == "price:>10"

    def test_lte_range(self) -> None:
        result = translate_filter_to_typesense({"price__lte": 100})
        assert result == "price:<=100"

    def test_lt_range(self) -> None:
        result = translate_filter_to_typesense({"price__lt": 200})
        assert result == "price:<200"

    def test_multiple_filters_joined_with_and(self) -> None:
        result = translate_filter_to_typesense({"city": "Madrid", "price__gte": 50})
        assert "&&" in result
        assert "city:=`Madrid`" in result
        assert "price:>=50" in result

    def test_string_passthrough(self) -> None:
        pre_built = "price:>=10 && city:=Madrid"
        assert translate_filter_to_typesense(pre_built) == pre_built

    def test_empty_dict_returns_empty_string(self) -> None:
        assert translate_filter_to_typesense({}) == ""

    def test_string_with_spaces_wrapped_in_backticks(self) -> None:
        result = translate_filter_to_typesense({"brand": "New Balance"})
        assert "`New Balance`" in result


# ---------------------------------------------------------------------------
# Sort translation
# ---------------------------------------------------------------------------


class TestSortTranslation:
    def test_descending_prefix_produces_desc(self) -> None:
        result = translate_sort_to_typesense(["-price"])
        assert result == "price:desc"

    def test_ascending_no_prefix_produces_asc(self) -> None:
        result = translate_sort_to_typesense(["name"])
        assert result == "name:asc"

    def test_multiple_fields_comma_joined(self) -> None:
        result = translate_sort_to_typesense(["-created_at", "name"])
        assert result == "created_at:desc,name:asc"

    def test_empty_list_returns_empty_string(self) -> None:
        assert translate_sort_to_typesense([]) == ""

    def test_string_input_treated_as_single_ascending_field(self) -> None:
        result = translate_sort_to_typesense("price")
        assert result == "price:asc"

    def test_typesense_native_format_passes_through(self) -> None:
        result = translate_sort_to_typesense(["price:desc"])
        assert result == "price:desc"


# ---------------------------------------------------------------------------
# Schema generation
# ---------------------------------------------------------------------------


class TestSchemaGeneration:
    def test_searchable_field_has_index_true(self) -> None:
        settings = {"searchableAttributes": ["title"], "filterableAttributes": [], "sortableAttributes": []}
        fields = _build_schema_fields(settings, {})
        title_field = next(f for f in fields if f["name"] == "title")
        assert title_field["index"] is True

    def test_filterable_field_has_facet_true(self) -> None:
        settings = {"searchableAttributes": [], "filterableAttributes": ["category"], "sortableAttributes": []}
        fields = _build_schema_fields(settings, {})
        cat_field = next(f for f in fields if f["name"] == "category")
        assert cat_field["facet"] is True

    def test_sortable_field_has_sort_true(self) -> None:
        settings = {"searchableAttributes": [], "filterableAttributes": [], "sortableAttributes": ["price"]}
        fields = _build_schema_fields(settings, {})
        price_field = next(f for f in fields if f["name"] == "price")
        assert price_field["sort"] is True

    def test_field_types_mapping_applied(self) -> None:
        settings = {"searchableAttributes": [], "filterableAttributes": ["price"], "sortableAttributes": []}
        fields = _build_schema_fields(settings, {"price": "float"})
        price_field = next(f for f in fields if f["name"] == "price")
        assert price_field["type"] == "float"

    def test_unmapped_field_defaults_to_string(self) -> None:
        settings = {"searchableAttributes": ["unknown_field"], "filterableAttributes": [], "sortableAttributes": []}
        fields = _build_schema_fields(settings, {})
        field = next(f for f in fields if f["name"] == "unknown_field")
        assert field["type"] == "string"

    def test_empty_settings_returns_empty_list(self) -> None:
        fields = _build_schema_fields({}, {})
        assert fields == []

    def test_field_in_all_three_sets(self) -> None:
        settings = {
            "searchableAttributes": ["name"],
            "filterableAttributes": ["name"],
            "sortableAttributes": ["name"],
        }
        fields = _build_schema_fields(settings, {})
        name_field = next(f for f in fields if f["name"] == "name")
        assert name_field["index"] is True
        assert name_field["facet"] is True
        assert name_field["sort"] is True


# ---------------------------------------------------------------------------
# Search response normalisation
# ---------------------------------------------------------------------------


class TestSearchResponseNormalisation:
    def test_hits_include_document_fields(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.documents.search.return_value = _ts_search_response(
            hits=[{"document": {"id": "1", "title": "Widget"}}],
            found=1,
        )
        result = backend.search("products", "widget")
        assert result["hits"][0]["id"] == "1"
        assert result["hits"][0]["title"] == "Widget"

    def test_estimated_total_hits_from_found(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.documents.search.return_value = _ts_search_response(
            found=42
        )
        result = backend.search("products", "")
        assert result["estimatedTotalHits"] == 42

    def test_processing_time_ms_from_search_time_ms(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.documents.search.return_value = _ts_search_response(
            search_time_ms=7
        )
        result = backend.search("products", "")
        assert result["processingTimeMs"] == 7

    def test_facet_distribution_built_from_facet_counts(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.documents.search.return_value = _ts_search_response(
            facet_counts=[
                {
                    "field_name": "category",
                    "counts": [
                        {"value": "books", "count": 10},
                        {"value": "games", "count": 5},
                    ],
                }
            ]
        )
        result = backend.search("products", "", facets=["category"])
        assert result["facetDistribution"] == {"category": {"books": 10, "games": 5}}

    def test_formatted_hits_not_in_response_without_highlight(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.documents.search.return_value = _ts_search_response(
            hits=[{"document": {"id": "1"}}], found=1
        )
        result = backend.search("products", "test")
        assert "formatted_hits" not in result

    def test_formatted_hits_populated_when_highlight_requested(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.documents.search.return_value = _ts_search_response(
            hits=[
                {
                    "document": {"id": "1", "title": "Running shoes"},
                    "highlights": [
                        {"field": "title", "snippet": "<mark>Running</mark> shoes"},
                    ],
                }
            ],
            found=1,
        )
        result = backend.search("products", "running", highlight_fields=["title"])
        assert result["formatted_hits"][0]["title"] == "<mark>Running</mark> shoes"

    def test_limit_and_offset_present_in_result(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.documents.search.return_value = _ts_search_response()
        result = backend.search("products", "", limit=10, offset=20)
        assert result["limit"] == 10
        assert result["offset"] == 20


# ---------------------------------------------------------------------------
# get_document
# ---------------------------------------------------------------------------


class TestGetDocument:
    def test_returns_document_with_id(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.documents.__getitem__.return_value.retrieve.return_value = {
            "id": "doc-42",
            "title": "Widget",
            "price": 9.99,
        }
        result = backend.get_document("products", "doc-42")
        assert result["id"] == "doc-42"
        assert result["title"] == "Widget"
        assert result["price"] == 9.99


# ---------------------------------------------------------------------------
# facet_search
# ---------------------------------------------------------------------------


class TestFacetSearch:
    def test_returns_sorted_value_count_list(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.documents.search.return_value = {
            "found": 0,
            "hits": [],
            "facet_counts": [
                {
                    "field_name": "colour",
                    "counts": [
                        {"value": "red", "count": 3},
                        {"value": "blue", "count": 10},
                        {"value": "green", "count": 1},
                    ],
                }
            ],
        }
        result = backend.facet_search("products", "colour")
        assert result[0] == {"value": "blue", "count": 10}
        assert result[1] == {"value": "red", "count": 3}
        assert result[2] == {"value": "green", "count": 1}

    def test_facet_query_added_when_provided(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.documents.search.return_value = {
            "found": 0,
            "hits": [],
            "facet_counts": [{"field_name": "colour", "counts": []}],
        }
        backend.facet_search("products", "colour", facet_query="bl")
        call_args = backend._client.collections.__getitem__.return_value.documents.search.call_args
        search_params = call_args[0][0]
        assert "facet_query" in search_params
        assert "bl" in search_params["facet_query"]

    def test_empty_result_when_no_facets_match(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.documents.search.return_value = {
            "found": 0,
            "hits": [],
            "facet_counts": [],
        }
        result = backend.facet_search("products", "colour")
        assert result == []


# ---------------------------------------------------------------------------
# similar_documents
# ---------------------------------------------------------------------------


class TestSimilarDocuments:
    def test_raises_not_implemented_error(self) -> None:
        backend = _make_backend()
        with pytest.raises(NotImplementedError, match="TypesenseBackend does not support similar_documents"):
            backend.similar_documents("products", "doc-1")


# ---------------------------------------------------------------------------
# compact
# ---------------------------------------------------------------------------


class TestCompact:
    def test_returns_empty_dict(self) -> None:
        backend = _make_backend()
        result = backend.compact("my-collection")
        assert result == {}

    def test_does_not_call_client(self) -> None:
        backend = _make_backend()
        backend.compact("my-collection")
        # Confirm no client calls were made.
        backend._client.collections.assert_not_called()


# ---------------------------------------------------------------------------
# update_documents
# ---------------------------------------------------------------------------


class TestUpdateDocuments:
    def test_uses_emplace_action(self) -> None:
        backend = _make_backend()
        docs = [{"id": "1", "price": 9.99}]
        backend._client.collections.__getitem__.return_value.documents.import_.return_value = [{"success": True}]
        backend.update_documents("products", docs)
        call_args = backend._client.collections.__getitem__.return_value.documents.import_.call_args
        action_params = call_args[0][1]
        assert action_params["action"] == "emplace"

    def test_returns_succeeded_and_failed_counts(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.documents.import_.return_value = [
            {"success": True},
            {"success": True},
            {"success": False, "error": "validation error"},
        ]
        result = backend.update_documents("products", [{"id": str(i)} for i in range(3)])
        assert result["succeeded"] == 2
        assert result["failed"] == 1


# ---------------------------------------------------------------------------
# swap_indexes (aliases)
# ---------------------------------------------------------------------------


class TestSwapIndexes:
    def test_upserts_alias_with_target_collection(self) -> None:
        backend = _make_backend()
        backend._client.aliases.upsert.return_value = {
            "collection_name": "products_v2",
            "name": "products",
        }
        backend.swap_indexes([("products", "products_v2")])
        backend._client.aliases.upsert.assert_called_once_with(
            "products",
            {"collection_name": "products_v2"},
        )

    def test_returns_dict_with_aliases_key(self) -> None:
        backend = _make_backend()
        backend._client.aliases.upsert.return_value = {"name": "products", "collection_name": "products_v2"}
        result = backend.swap_indexes([("products", "products_v2")])
        assert "aliases" in result
        assert len(result["aliases"]) == 1

    def test_multiple_pairs_makes_multiple_upsert_calls(self) -> None:
        backend = _make_backend()
        backend._client.aliases.upsert.return_value = {}
        backend.swap_indexes([("a", "a_v2"), ("b", "b_v2")])
        assert backend._client.aliases.upsert.call_count == 2


# ---------------------------------------------------------------------------
# get_task
# ---------------------------------------------------------------------------


class TestGetTask:
    def test_returns_stub_with_succeeded_status(self) -> None:
        backend = _make_backend()
        result = backend.get_task("task-123")
        assert result["taskUid"] == "task-123"
        assert result["status"] == "succeeded"

    def test_does_not_call_client(self) -> None:
        backend = _make_backend()
        backend.get_task("task-999")
        backend._client.assert_not_called()


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_returns_true_when_health_ok(self) -> None:
        backend = _make_backend()
        backend._client.operations.perform.return_value = {"ok": True}
        assert backend.health() is True

    def test_returns_false_when_health_not_ok(self) -> None:
        backend = _make_backend()
        backend._client.operations.perform.return_value = {"ok": False}
        assert backend.health() is False

    def test_returns_false_on_backend_error(self) -> None:
        backend = _make_backend()
        backend._client.operations.perform.side_effect = Exception("connection refused")
        assert backend.health() is False


# ---------------------------------------------------------------------------
# multi_search
# ---------------------------------------------------------------------------


class TestMultiSearch:
    def test_sends_all_queries_to_multi_search(self) -> None:
        backend = _make_backend()
        backend._client.multi_search.perform.return_value = {
            "results": [
                _ts_search_response(hits=[{"document": {"id": "1", "title": "A"}}], found=1),
                _ts_search_response(hits=[{"document": {"id": "2", "title": "B"}}], found=1),
            ]
        }
        queries = [
            {"uid": "products", "query": "shoes"},
            {"uid": "articles", "query": "news"},
        ]
        results = backend.multi_search(queries)
        assert len(results) == 2
        assert results[0]["hits"][0]["title"] == "A"
        assert results[1]["hits"][0]["title"] == "B"

    def test_searches_payload_contains_both_collections(self) -> None:
        backend = _make_backend()
        backend._client.multi_search.perform.return_value = {"results": [_ts_search_response(), _ts_search_response()]}
        queries = [
            {"uid": "products", "query": "shoes"},
            {"uid": "articles", "query": "news"},
        ]
        backend.multi_search(queries)
        call_args = backend._client.multi_search.perform.call_args
        searches = call_args[0][0]["searches"]
        collections = [s["collection"] for s in searches]
        assert "products" in collections
        assert "articles" in collections

    def test_filters_translated_in_multi_search(self) -> None:
        backend = _make_backend()
        backend._client.multi_search.perform.return_value = {"results": [_ts_search_response()]}
        queries = [{"uid": "products", "query": "shoes", "filter": {"price__gte": 50}}]
        backend.multi_search(queries)
        call_args = backend._client.multi_search.perform.call_args
        search = call_args[0][0]["searches"][0]
        assert search["filter_by"] == "price:>=50"

    def test_returns_normalised_format(self) -> None:
        backend = _make_backend()
        backend._client.multi_search.perform.return_value = {
            "results": [_ts_search_response(found=7, search_time_ms=2)]
        }
        results = backend.multi_search([{"uid": "products", "query": "test"}])
        assert results[0]["estimatedTotalHits"] == 7
        assert results[0]["processingTimeMs"] == 2


# ---------------------------------------------------------------------------
# Error mapping (_call helper)
# ---------------------------------------------------------------------------


class TestErrorMapping:
    def test_unauthorised_maps_to_search_backend_error(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.retrieve.side_effect = (
            typesense.exceptions.RequestUnauthorized("Unauthorised")
        )
        with pytest.raises(SearchBackendError, match="unauthorised"):
            backend.get_settings("my-collection")

    def test_object_not_found_maps_to_index_not_found_error(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.retrieve.side_effect = typesense.exceptions.ObjectNotFound(
            "Not found"
        )
        with pytest.raises(IndexNotFoundError):
            backend.get_settings("missing-collection")

    def test_service_unavailable_maps_to_search_timeout_error(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.retrieve.side_effect = (
            typesense.exceptions.ServiceUnavailable("Service unavailable")
        )
        with pytest.raises(SearchTimeoutError, match="service unavailable"):
            backend.get_settings("my-collection")

    def test_generic_typesense_error_maps_to_search_backend_error(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.retrieve.side_effect = (
            typesense.exceptions.TypesenseClientError("Some error")
        )
        with pytest.raises(SearchBackendError):
            backend.get_settings("my-collection")

    def test_connection_error_maps_to_search_backend_error(self) -> None:
        backend = _make_backend()
        backend._client.collections.__getitem__.return_value.retrieve.side_effect = ConnectionError(
            "connection refused"
        )
        with pytest.raises(SearchBackendError):
            backend.get_settings("my-collection")

    def test_health_returns_false_on_service_unavailable(self) -> None:
        backend = _make_backend()
        backend._client.operations.perform.side_effect = typesense.exceptions.ServiceUnavailable("down")
        assert backend.health() is False
