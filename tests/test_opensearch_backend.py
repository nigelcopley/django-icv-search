"""Tests for the OpenSearch backend.

All tests are skipped when ``opensearch-py`` is not installed. SDK calls are
fully mocked — no live cluster is required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

try:
    import opensearchpy  # noqa: F401

    HAS_OPENSEARCHPY = True
except ImportError:
    HAS_OPENSEARCHPY = False

pytestmark = pytest.mark.skipif(not HAS_OPENSEARCHPY, reason="opensearch-py not installed")

# ---------------------------------------------------------------------------
# Import the module under test only when opensearch-py is available so that
# collection does not fail on machines without the SDK.
# ---------------------------------------------------------------------------
if HAS_OPENSEARCHPY:
    from icv_search.backends.opensearch import (
        OpenSearchBackend,
        translate_filter_to_opensearch,
        translate_sort_to_opensearch,
    )
    from icv_search.exceptions import IndexNotFoundError, SearchBackendError, SearchTimeoutError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_backend(**kwargs: Any) -> OpenSearchBackend:
    """Construct an OpenSearchBackend with a mocked opensearch-py client."""
    with patch("icv_search.backends.opensearch.OpenSearch") as mock_cls:
        mock_cls.return_value = MagicMock()
        backend = OpenSearchBackend(
            url="http://localhost:9200",
            api_key="test-key",
            **kwargs,
        )
    # Replace the client with a fresh MagicMock for assertion access.
    backend._client = MagicMock()
    return backend


def _os_search_response(
    hits: list[dict[str, Any]] | None = None,
    total: int = 0,
    took: int = 5,
    aggregations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal OpenSearch _search response dict."""
    raw_hits = hits or []
    return {
        "took": took,
        "hits": {
            "total": {"value": total},
            "hits": raw_hits,
        },
        "aggregations": aggregations or {},
    }


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_raises_improperly_configured_when_sdk_missing(self) -> None:
        """ImproperlyConfigured is raised when opensearch-py is not installed."""
        with patch("icv_search.backends.opensearch._HAS_OPENSEARCH", False):
            from django.core.exceptions import ImproperlyConfigured

            with pytest.raises(ImproperlyConfigured, match="opensearch-py is required"):
                OpenSearchBackend(url="http://localhost:9200", api_key="key")

    def test_constructs_client_with_basic_auth(self) -> None:
        """basic_auth kwarg is forwarded to the OpenSearch client as http_auth."""
        with patch("icv_search.backends.opensearch.OpenSearch") as mock_cls:
            mock_cls.return_value = MagicMock()
            OpenSearchBackend(
                url="https://host:9200",
                api_key="",
                basic_auth=("admin", "secret"),
            )
        _, call_kwargs = mock_cls.call_args
        assert call_kwargs["http_auth"] == ("admin", "secret")

    def test_constructs_client_with_api_key_as_password(self) -> None:
        """When only api_key is set, http_auth is ('', api_key)."""
        with patch("icv_search.backends.opensearch.OpenSearch") as mock_cls:
            mock_cls.return_value = MagicMock()
            OpenSearchBackend(url="http://localhost:9200", api_key="my-api-key")
        _, call_kwargs = mock_cls.call_args
        assert call_kwargs["http_auth"] == ("", "my-api-key")

    def test_infers_use_ssl_from_url_scheme(self) -> None:
        """use_ssl defaults to True when URL scheme is https."""
        with patch("icv_search.backends.opensearch.OpenSearch") as mock_cls:
            mock_cls.return_value = MagicMock()
            OpenSearchBackend(url="https://host:9200", api_key="")
        _, call_kwargs = mock_cls.call_args
        assert call_kwargs["use_ssl"] is True

    def test_verify_certs_forwarded(self) -> None:
        """verify_certs kwarg is forwarded to the OpenSearch client."""
        with patch("icv_search.backends.opensearch.OpenSearch") as mock_cls:
            mock_cls.return_value = MagicMock()
            OpenSearchBackend(url="http://localhost:9200", api_key="", verify_certs=False)
        _, call_kwargs = mock_cls.call_args
        assert call_kwargs["verify_certs"] is False


# ---------------------------------------------------------------------------
# Error mapping (_call helper)
# ---------------------------------------------------------------------------


class TestErrorMapping:
    def test_connection_timeout_maps_to_search_timeout_error(self) -> None:
        backend = _make_backend()
        backend._client.indices.create.side_effect = opensearchpy.ConnectionTimeout(
            "GET", "/indexes", "timeout exceeded"
        )
        with pytest.raises(SearchTimeoutError):
            backend.create_index("my-index")

    def test_connection_error_maps_to_search_backend_error(self) -> None:
        backend = _make_backend()
        backend._client.indices.delete.side_effect = opensearchpy.ConnectionError(
            "DELETE", "/indexes/my-index", Exception("conn refused")
        )
        with pytest.raises(SearchBackendError, match="unreachable"):
            backend.delete_index("my-index")

    def test_transport_error_404_with_index_not_found_maps_to_index_not_found_error(self) -> None:
        backend = _make_backend()
        exc = opensearchpy.TransportError(404, "index_not_found_exception", {"reason": "index_not_found_exception"})
        backend._client.indices.delete.side_effect = exc
        with pytest.raises(IndexNotFoundError):
            backend.delete_index("missing-index")

    def test_transport_error_500_maps_to_search_backend_error(self) -> None:
        backend = _make_backend()
        exc = opensearchpy.TransportError(500, "internal_server_error", {})
        backend._client.indices.stats.side_effect = exc
        with pytest.raises(SearchBackendError, match="500"):
            backend.get_stats("my-index")

    def test_health_returns_false_on_backend_error(self) -> None:
        backend = _make_backend()
        backend._client.cluster.health.side_effect = opensearchpy.ConnectionError(
            "GET", "/_cluster/health", Exception("down")
        )
        assert backend.health() is False


# ---------------------------------------------------------------------------
# Filter translation
# ---------------------------------------------------------------------------


class TestFilterTranslation:
    def test_scalar_string_produces_term_clause(self) -> None:
        result = translate_filter_to_opensearch({"city": "Madrid"})
        assert result == {"term": {"city": "Madrid"}}

    def test_boolean_produces_term_clause(self) -> None:
        result = translate_filter_to_opensearch({"is_active": True})
        assert result == {"term": {"is_active": True}}

    def test_list_produces_terms_clause(self) -> None:
        result = translate_filter_to_opensearch({"category": ["books", "games"]})
        assert result == {"terms": {"category": ["books", "games"]}}

    def test_none_value_produces_must_not_exists(self) -> None:
        result = translate_filter_to_opensearch({"brand": None})
        assert result == {"bool": {"must_not": [{"exists": {"field": "brand"}}]}}

    def test_gte_produces_range_clause(self) -> None:
        result = translate_filter_to_opensearch({"price__gte": 50})
        assert result == {"range": {"price": {"gte": 50}}}

    def test_gt_produces_range_clause(self) -> None:
        result = translate_filter_to_opensearch({"price__gt": 10})
        assert result == {"range": {"price": {"gt": 10}}}

    def test_lte_produces_range_clause(self) -> None:
        result = translate_filter_to_opensearch({"price__lte": 100})
        assert result == {"range": {"price": {"lte": 100}}}

    def test_lt_produces_range_clause(self) -> None:
        result = translate_filter_to_opensearch({"price__lt": 200})
        assert result == {"range": {"price": {"lt": 200}}}

    def test_multiple_filters_produce_bool_filter(self) -> None:
        result = translate_filter_to_opensearch({"city": "Madrid", "price__gte": 50})
        assert result["bool"]["filter"]
        clauses = result["bool"]["filter"]
        assert any("term" in c for c in clauses)
        assert any("range" in c for c in clauses)

    def test_dual_mapped_field_targets_keyword_subfield(self) -> None:
        result = translate_filter_to_opensearch({"brand": "Nike"}, dual_mapped_fields={"brand"})
        assert result == {"term": {"brand.keyword": "Nike"}}

    def test_dual_mapped_list_targets_keyword_subfield(self) -> None:
        result = translate_filter_to_opensearch({"brand": ["Nike", "Adidas"]}, dual_mapped_fields={"brand"})
        assert result == {"terms": {"brand.keyword": ["Nike", "Adidas"]}}

    def test_passthrough_of_existing_bool_dict(self) -> None:
        pre_built = {"bool": {"must": [{"term": {"x": 1}}]}}
        assert translate_filter_to_opensearch(pre_built) is pre_built

    def test_empty_dict_returns_empty(self) -> None:
        assert translate_filter_to_opensearch({}) == {}


# ---------------------------------------------------------------------------
# Sort translation
# ---------------------------------------------------------------------------


class TestSortTranslation:
    def test_descending_prefix(self) -> None:
        result = translate_sort_to_opensearch(["-price"])
        assert result == [{"price": {"order": "desc", "missing": "_last"}}]

    def test_ascending_no_prefix(self) -> None:
        result = translate_sort_to_opensearch(["name"])
        assert result == [{"name": {"order": "asc", "missing": "_last"}}]

    def test_multiple_fields(self) -> None:
        result = translate_sort_to_opensearch(["-created_at", "name"])
        assert result[0] == {"created_at": {"order": "desc", "missing": "_last"}}
        assert result[1] == {"name": {"order": "asc", "missing": "_last"}}

    def test_empty_list_returns_empty(self) -> None:
        assert translate_sort_to_opensearch([]) == []

    def test_string_input_wrapped_in_list(self) -> None:
        result = translate_sort_to_opensearch("price")
        assert result == [{"price": {"order": "asc", "missing": "_last"}}]


# ---------------------------------------------------------------------------
# Search response normalisation
# ---------------------------------------------------------------------------


class TestSearchResponseNormalisation:
    def test_hits_include_id_from_hit_id(self) -> None:
        backend = _make_backend()
        raw = _os_search_response(
            hits=[{"_id": "42", "_source": {"title": "Thing"}}],
            total=1,
        )
        backend._client.search.return_value = raw
        result = backend.search("my-index", "thing")
        assert result["hits"][0]["id"] == "42"
        assert result["hits"][0]["title"] == "Thing"

    def test_estimated_total_hits(self) -> None:
        backend = _make_backend()
        raw = _os_search_response(total=500)
        backend._client.search.return_value = raw
        result = backend.search("my-index", "")
        assert result["estimatedTotalHits"] == 500

    def test_processing_time_ms_from_took(self) -> None:
        backend = _make_backend()
        raw = _os_search_response(took=12)
        backend._client.search.return_value = raw
        result = backend.search("my-index", "")
        assert result["processingTimeMs"] == 12

    def test_facet_distribution_built_from_aggregations(self) -> None:
        backend = _make_backend()
        raw = _os_search_response(
            aggregations={
                "category": {
                    "buckets": [
                        {"key": "books", "doc_count": 10},
                        {"key": "games", "doc_count": 5},
                    ]
                }
            }
        )
        backend._client.search.return_value = raw
        result = backend.search("my-index", "", facets=["category"])
        assert result["facetDistribution"] == {"category": {"books": 10, "games": 5}}

    def test_formatted_hits_not_in_response_without_highlight(self) -> None:
        backend = _make_backend()
        raw = _os_search_response(hits=[{"_id": "1", "_source": {}}], total=1)
        backend._client.search.return_value = raw
        result = backend.search("my-index", "test")
        assert "formatted_hits" not in result

    def test_formatted_hits_populated_when_highlight_requested(self) -> None:
        backend = _make_backend()
        raw = _os_search_response(
            hits=[
                {
                    "_id": "1",
                    "_source": {"title": "Running shoes"},
                    "highlight": {"title": ["<mark>Running</mark> shoes"]},
                }
            ],
            total=1,
        )
        backend._client.search.return_value = raw
        result = backend.search("my-index", "running", highlight_fields=["title"])
        assert result["formatted_hits"][0]["title"] == "<mark>Running</mark> shoes"


# ---------------------------------------------------------------------------
# get_document
# ---------------------------------------------------------------------------


class TestGetDocument:
    def test_returns_source_merged_with_id(self) -> None:
        backend = _make_backend()
        backend._client.get.return_value = {
            "_id": "doc-42",
            "_source": {"title": "Widget", "price": 9.99},
        }
        result = backend.get_document("products", "doc-42")
        assert result["id"] == "doc-42"
        assert result["title"] == "Widget"
        assert result["price"] == 9.99

    def test_calls_client_get_with_correct_args(self) -> None:
        backend = _make_backend()
        backend._client.get.return_value = {"_id": "1", "_source": {}}
        backend.get_document("my-index", "1")
        backend._client.get.assert_called_once_with(index="my-index", id="1")


# ---------------------------------------------------------------------------
# facet_search
# ---------------------------------------------------------------------------


class TestFacetSearch:
    def test_returns_sorted_value_count_list(self) -> None:
        backend = _make_backend()
        backend._client.search.return_value = {
            "aggregations": {
                "facet_values": {
                    "buckets": [
                        {"key": "red", "doc_count": 3},
                        {"key": "blue", "doc_count": 10},
                        {"key": "green", "doc_count": 1},
                    ]
                }
            }
        }
        result = backend.facet_search("products", "colour")
        assert result[0] == {"value": "blue", "count": 10}
        assert result[1] == {"value": "red", "count": 3}
        assert result[2] == {"value": "green", "count": 1}

    def test_include_regex_added_when_facet_query_provided(self) -> None:
        backend = _make_backend()
        backend._client.search.return_value = {"aggregations": {"facet_values": {"buckets": []}}}
        backend.facet_search("products", "colour", facet_query="bl")
        call_body = backend._client.search.call_args[1]["body"]
        agg_terms = call_body["aggs"]["facet_values"]["terms"]
        assert "include" in agg_terms
        assert "bl" in agg_terms["include"]


# ---------------------------------------------------------------------------
# similar_documents
# ---------------------------------------------------------------------------


class TestSimilarDocuments:
    def test_uses_more_like_this_query(self) -> None:
        backend = _make_backend()
        backend._client.search.return_value = _os_search_response()
        backend.similar_documents("products", "doc-1")
        call_body = backend._client.search.call_args[1]["body"]
        assert "more_like_this" in call_body["query"]
        mlt = call_body["query"]["more_like_this"]
        assert mlt["like"][0]["_id"] == "doc-1"
        assert mlt["like"][0]["_index"] == "products"

    def test_returns_normalised_search_response(self) -> None:
        backend = _make_backend()
        backend._client.search.return_value = _os_search_response(
            hits=[{"_id": "doc-2", "_source": {"title": "Similar"}}],
            total=1,
        )
        result = backend.similar_documents("products", "doc-1")
        assert result["estimatedTotalHits"] == 1
        assert result["hits"][0]["id"] == "doc-2"


# ---------------------------------------------------------------------------
# compact
# ---------------------------------------------------------------------------


class TestCompact:
    def test_calls_forcemerge(self) -> None:
        backend = _make_backend()
        backend._client.indices.forcemerge.return_value = {"_shards": {"successful": 1}}
        result = backend.compact("my-index")
        backend._client.indices.forcemerge.assert_called_once_with(index="my-index")
        assert "_shards" in result


# ---------------------------------------------------------------------------
# update_documents
# ---------------------------------------------------------------------------


class TestUpdateDocuments:
    def test_uses_update_bulk_action(self) -> None:
        backend = _make_backend()
        docs = [{"id": "1", "price": 9.99}]

        with patch("icv_search.backends.opensearch.opensearchpy.helpers.bulk") as mock_bulk:
            mock_bulk.return_value = (1, [])
            backend.update_documents("products", docs)

        actions = mock_bulk.call_args[0][1]
        assert actions[0]["_op_type"] == "update"
        assert actions[0]["doc"] == docs[0]
        assert actions[0]["_id"] == "1"

    def test_returns_succeeded_count(self) -> None:
        backend = _make_backend()
        with patch("icv_search.backends.opensearch.opensearchpy.helpers.bulk") as mock_bulk:
            mock_bulk.return_value = (3, [])
            result = backend.update_documents("products", [{"id": str(i)} for i in range(3)])
        assert result["succeeded"] == 3
        assert result["failed"] == 0


# ---------------------------------------------------------------------------
# swap_indexes
# ---------------------------------------------------------------------------


class TestSwapIndexes:
    def test_uses_update_aliases(self) -> None:
        backend = _make_backend()
        # Simulate index_a being a real index with an alias.
        backend._client.indices.get_alias.return_value = {"products_v1": {"aliases": {"products": {}}}}
        backend._client.indices.update_aliases.return_value = {"acknowledged": True}
        backend.swap_indexes([("products", "products_v2")])
        body = backend._client.indices.update_aliases.call_args[1]["body"]
        actions = body["actions"]
        assert any(a.get("remove", {}).get("alias") == "products" for a in actions)
        assert any(
            a.get("add", {}).get("alias") == "products" and a.get("add", {}).get("index") == "products_v2"
            for a in actions
        )

    def test_creates_live_alias_when_index_a_is_real_index(self) -> None:
        backend = _make_backend()
        # Simulate no alias named "products" pointing anywhere.
        backend._client.indices.get_alias.return_value = {
            "products": {"aliases": {}}  # real index, no alias
        }
        backend._client.indices.update_aliases.return_value = {"acknowledged": True}
        backend.swap_indexes([("products", "products_v2")])
        body = backend._client.indices.update_aliases.call_args[1]["body"]
        actions = body["actions"]
        assert any(a.get("add", {}).get("alias") == "products_live" for a in actions)


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_returns_true_for_green_cluster(self) -> None:
        backend = _make_backend()
        backend._client.cluster.health.return_value = {"status": "green"}
        assert backend.health() is True

    def test_returns_true_for_yellow_cluster(self) -> None:
        backend = _make_backend()
        backend._client.cluster.health.return_value = {"status": "yellow"}
        assert backend.health() is True

    def test_returns_false_for_red_cluster(self) -> None:
        backend = _make_backend()
        backend._client.cluster.health.return_value = {"status": "red"}
        assert backend.health() is False
