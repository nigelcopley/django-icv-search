"""Tests for the Apache Solr backend.

All tests are skipped when ``pysolr`` is not installed. All SDK and HTTP
calls are fully mocked — no live Solr instance is required.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

try:
    import pysolr  # noqa: F401

    HAS_PYSOLR = True
except ImportError:
    HAS_PYSOLR = False

pytestmark = pytest.mark.skipif(not HAS_PYSOLR, reason="pysolr not installed")

# ---------------------------------------------------------------------------
# Import the module under test only when pysolr is available so that
# collection does not fail on machines without the SDK.
# ---------------------------------------------------------------------------
if HAS_PYSOLR:
    from icv_search.backends.filters import translate_filter_to_solr, translate_sort_to_solr
    from icv_search.backends.solr import SolrBackend
    from icv_search.exceptions import IndexNotFoundError, SearchBackendError, SearchTimeoutError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_backend(**kwargs: Any) -> SolrBackend:
    """Construct a SolrBackend with all pysolr/httpx construction mocked."""
    with (
        patch("icv_search.backends.solr.pysolr") as _mock_pysolr,
        patch("icv_search.backends.solr.httpx.Client") as _mock_http_cls,
    ):
        _mock_http_cls.return_value = MagicMock()
        backend = SolrBackend(
            url="http://localhost:8983/solr",
            api_key="",
            **kwargs,
        )
    # Replace internal HTTP client with a fresh MagicMock.
    backend._http = MagicMock()
    return backend


def _solr_results(
    docs: list[dict[str, Any]] | None = None,
    hits: int = 0,
    qtime: int = 5,
    facets: dict[str, Any] | None = None,
    highlighting: dict[str, Any] | None = None,
    next_cursor: str | None = None,
) -> MagicMock:
    """Build a minimal pysolr Results-like mock."""
    result = MagicMock()
    result.docs = docs or []
    result.hits = hits
    result.qtime = qtime
    result.facets = facets or {}
    result.highlighting = highlighting or {}
    if next_cursor is not None:
        result.nextCursorMark = next_cursor
    else:
        del result.nextCursorMark
    return result


def _http_response(status: int = 200, body: dict[str, Any] | None = None) -> MagicMock:
    """Build a minimal httpx Response mock."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body or {}
    resp.text = json.dumps(body or {})
    return resp


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_raises_improperly_configured_when_sdk_missing(self) -> None:
        """ImproperlyConfigured is raised when pysolr is not installed."""
        from django.core.exceptions import ImproperlyConfigured

        with (
            patch("icv_search.backends.solr._PYSOLR_AVAILABLE", False),
            pytest.raises(ImproperlyConfigured, match="pysolr"),
        ):
            SolrBackend(url="http://localhost:8983/solr", api_key="")

    def test_stores_constructor_params(self) -> None:
        """Constructor stores url, collection_config, commit_within."""
        backend = _make_backend(collection_config="my_config", commit_within=500)
        assert backend.url == "http://localhost:8983/solr"
        assert backend.collection_config == "my_config"
        assert backend.commit_within == 500

    def test_trailing_slash_stripped_from_url(self) -> None:
        """Trailing slash is stripped from the base URL."""
        backend = _make_backend()
        assert not backend.url.endswith("/")

    def test_auth_tuple_set_when_api_key_provided(self) -> None:
        """Auth tuple is (empty-username, api_key) when api_key is non-empty."""
        with (
            patch("icv_search.backends.solr.pysolr"),
            patch("icv_search.backends.solr.httpx.Client"),
        ):
            backend = SolrBackend(url="http://localhost:8983/solr", api_key="secret")
        assert backend._auth == ("", "secret")

    def test_auth_none_when_api_key_empty(self) -> None:
        """Auth is None when api_key is empty string."""
        backend = _make_backend()
        assert backend._auth is None

    def test_solrcloud_client_created_when_zookeeper_hosts_provided(self) -> None:
        """A SolrCloud client is created when zookeeper_hosts is non-empty."""
        with (
            patch("icv_search.backends.solr.pysolr") as mock_pysolr,
            patch("icv_search.backends.solr.httpx.Client"),
        ):
            mock_zk = MagicMock()
            mock_pysolr.ZooKeeper.return_value = mock_zk
            backend = SolrBackend(
                url="http://localhost:8983/solr",
                api_key="",
                zookeeper_hosts="zoo1:2181",
            )
        assert backend._zookeeper is mock_zk


# ---------------------------------------------------------------------------
# Filter translation
# ---------------------------------------------------------------------------


class TestTranslateFilterToSolr:
    def test_simple_string_equality(self) -> None:
        assert translate_filter_to_solr({"city": "Madrid"}) == ["city:Madrid"]

    def test_string_with_spaces_is_quoted(self) -> None:
        result = translate_filter_to_solr({"city": "New York"})
        assert result == ['city:"New York"']

    def test_boolean_true(self) -> None:
        assert translate_filter_to_solr({"is_active": True}) == ["is_active:true"]

    def test_boolean_false(self) -> None:
        assert translate_filter_to_solr({"is_active": False}) == ["is_active:false"]

    def test_numeric_equality(self) -> None:
        assert translate_filter_to_solr({"price": 150}) == ["price:150"]

    def test_list_produces_or_clause(self) -> None:
        result = translate_filter_to_solr({"category": ["a", "b"]})
        assert result == ["category:(a OR b)"]

    def test_none_produces_not_exists_clause(self) -> None:
        assert translate_filter_to_solr({"field": None}) == ["-field:[* TO *]"]

    def test_gte_operator(self) -> None:
        assert translate_filter_to_solr({"price__gte": 10}) == ["price:[10 TO *]"]

    def test_gt_operator(self) -> None:
        assert translate_filter_to_solr({"price__gt": 10}) == ["price:{10 TO *}"]

    def test_lte_operator(self) -> None:
        assert translate_filter_to_solr({"price__lte": 100}) == ["price:[* TO 100]"]

    def test_lt_operator(self) -> None:
        assert translate_filter_to_solr({"price__lt": 100}) == ["price:[* TO 100}"]

    def test_multiple_keys_produce_multiple_fq(self) -> None:
        result = translate_filter_to_solr({"city": "Madrid", "is_active": True})
        assert "city:Madrid" in result
        assert "is_active:true" in result
        assert len(result) == 2

    def test_passthrough_string(self) -> None:
        assert translate_filter_to_solr("city:Madrid") == ["city:Madrid"]

    def test_passthrough_list(self) -> None:
        raw = ["city:Madrid", "is_active:true"]
        assert translate_filter_to_solr(raw) == raw

    def test_empty_dict_returns_empty_list(self) -> None:
        assert translate_filter_to_solr({}) == []

    def test_empty_string_returns_empty_list(self) -> None:
        assert translate_filter_to_solr("") == []


# ---------------------------------------------------------------------------
# Sort translation
# ---------------------------------------------------------------------------


class TestTranslateSortToSolr:
    def test_single_ascending_field(self) -> None:
        assert translate_sort_to_solr(["name"]) == "name asc"

    def test_single_descending_field(self) -> None:
        assert translate_sort_to_solr(["-price"]) == "price desc"

    def test_multiple_fields(self) -> None:
        assert translate_sort_to_solr(["-price", "name"]) == "price desc, name asc"

    def test_score_descending(self) -> None:
        assert translate_sort_to_solr(["-score", "title"]) == "score desc, title asc"

    def test_passthrough_string(self) -> None:
        assert translate_sort_to_solr("price desc, name asc") == "price desc, name asc"

    def test_empty_list_returns_empty_string(self) -> None:
        assert translate_sort_to_solr([]) == ""


# ---------------------------------------------------------------------------
# create_index
# ---------------------------------------------------------------------------


class TestCreateIndex:
    def test_posts_to_collections_api(self) -> None:
        backend = _make_backend(collection_config="my_config")
        backend._http.request.return_value = _http_response(200, {"responseHeader": {"status": 0}})

        backend.create_index("products")

        call_args = backend._http.request.call_args
        assert call_args[0][0] == "POST"
        assert "/api/collections" in call_args[0][1]

    def test_payload_includes_config_and_uid(self) -> None:
        backend = _make_backend(collection_config="icv_managed")
        backend._http.request.return_value = _http_response(200, {})

        backend.create_index("products")

        payload = backend._http.request.call_args[1]["json"]
        assert payload["name"] == "products"
        assert payload["config"] == "icv_managed"


# ---------------------------------------------------------------------------
# delete_index
# ---------------------------------------------------------------------------


class TestDeleteIndex:
    def test_deletes_collection_via_api(self) -> None:
        backend = _make_backend()
        backend._http.request.return_value = _http_response(200, {})

        backend.delete_index("products")

        call_args = backend._http.request.call_args
        assert call_args[0][0] == "DELETE"
        assert "products" in call_args[0][1]

    def test_evicts_cached_client(self) -> None:
        backend = _make_backend()
        backend._http.request.return_value = _http_response(200, {})
        backend._clients["products"] = MagicMock()  # Seed the cache.

        backend.delete_index("products")

        assert "products" not in backend._clients

    def test_raises_index_not_found_on_404(self) -> None:
        backend = _make_backend()
        backend._http.request.return_value = _http_response(404)

        with pytest.raises(IndexNotFoundError):
            backend.delete_index("missing")


# ---------------------------------------------------------------------------
# update_settings
# ---------------------------------------------------------------------------


class TestUpdateSettings:
    def test_searchable_attrs_stored_internally(self) -> None:
        backend = _make_backend()
        backend.update_settings("products", {"searchableAttributes": ["title", "desc"]})
        assert backend._searchable_attrs["products"] == ["title", "desc"]

    def test_synonyms_pushed_to_managed_resource(self) -> None:
        backend = _make_backend()
        backend._http.request.return_value = _http_response(200, {})

        backend.update_settings("products", {"synonyms": ["quick,fast"]})

        call_args = backend._http.request.call_args
        assert "synonyms" in call_args[0][1]

    def test_stop_words_pushed_to_managed_resource(self) -> None:
        backend = _make_backend()
        backend._http.request.return_value = _http_response(200, {})

        backend.update_settings("products", {"stopWords": ["the", "a"]})

        call_args = backend._http.request.call_args
        assert "stopwords" in call_args[0][1]

    def test_unsupported_settings_in_skipped_list(self) -> None:
        backend = _make_backend()
        result = backend.update_settings("products", {"rankingRules": ["words"], "typoTolerance": {}})
        assert "rankingRules" in result["skipped"]
        assert "typoTolerance" in result["skipped"]

    def test_filterable_sortable_attrs_in_skipped_list(self) -> None:
        backend = _make_backend()
        result = backend.update_settings(
            "products", {"filterableAttributes": ["price"], "sortableAttributes": ["name"]}
        )
        assert "filterableAttributes" in result["skipped"]
        assert "sortableAttributes" in result["skipped"]

    def test_applied_list_populated_for_supported_settings(self) -> None:
        backend = _make_backend()
        result = backend.update_settings("products", {"searchableAttributes": ["title"]})
        assert "searchableAttributes" in result["applied"]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_empty_query_becomes_star_star(self) -> None:
        """An empty query string is translated to *:* for Solr."""
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results()
        backend._clients["products"] = mock_solr

        backend.search("products", "")

        call_args = mock_solr.search.call_args
        assert call_args[0][0] == "*:*"

    def test_deftype_edismax_is_set(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results()
        backend._clients["products"] = mock_solr

        backend.search("products", "shoes")

        kwargs = mock_solr.search.call_args[1]
        assert kwargs["defType"] == "edismax"

    def test_filter_dict_translated_to_fq(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results()
        backend._clients["products"] = mock_solr

        backend.search("products", "shoes", filter={"is_active": True})

        kwargs = mock_solr.search.call_args[1]
        assert "fq" in kwargs
        assert "is_active:true" in kwargs["fq"]

    def test_sort_list_translated_to_sort_string(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results()
        backend._clients["products"] = mock_solr

        backend.search("products", "shoes", sort=["-price", "name"])

        kwargs = mock_solr.search.call_args[1]
        assert kwargs["sort"] == "price desc, name asc"

    def test_limit_maps_to_rows(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results()
        backend._clients["products"] = mock_solr

        backend.search("products", "shoes", limit=50)

        kwargs = mock_solr.search.call_args[1]
        assert kwargs["rows"] == 50

    def test_offset_maps_to_start(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results()
        backend._clients["products"] = mock_solr

        backend.search("products", "shoes", offset=40)

        kwargs = mock_solr.search.call_args[1]
        assert kwargs["start"] == 40

    def test_attributes_to_retrieve_maps_to_fl(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results()
        backend._clients["products"] = mock_solr

        backend.search("products", "shoes", attributesToRetrieve=["title", "price"])

        kwargs = mock_solr.search.call_args[1]
        fl_fields = set(kwargs["fl"].split(","))
        assert "id" in fl_fields  # BR-010 — id always included
        assert "title" in fl_fields
        assert "price" in fl_fields

    def test_facets_list_builds_json_facet_param(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results()
        backend._clients["products"] = mock_solr

        backend.search("products", "shoes", facets=["category", "brand"])

        kwargs = mock_solr.search.call_args[1]
        assert "json.facet" in kwargs
        facet_def = json.loads(kwargs["json.facet"])
        assert "category" in facet_def
        assert "brand" in facet_def

    def test_json_facet_param_overrides_facets_list(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results()
        backend._clients["products"] = mock_solr

        custom_facet = {"my_facet": {"type": "range", "field": "price"}}
        backend.search("products", "shoes", facets=["category"], json_facet=custom_facet)

        kwargs = mock_solr.search.call_args[1]
        facet_def = json.loads(kwargs["json.facet"])
        assert "my_facet" in facet_def
        assert "category" not in facet_def

    def test_highlighting_params_set_when_fields_provided(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results()
        backend._clients["products"] = mock_solr

        backend.search(
            "products", "shoes", attributesToHighlight=["title"], highlightPreTag="<mark>", highlightPostTag="</mark>"
        )

        kwargs = mock_solr.search.call_args[1]
        assert kwargs["hl"] == "true"
        assert kwargs["hl.method"] == "unified"
        assert "title" in kwargs["hl.fl"]
        assert kwargs["hl.tag.pre"] == "<mark>"
        assert kwargs["hl.tag.post"] == "</mark>"

    def test_cursor_mark_appended_to_kwargs(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        raw = _solr_results()
        raw.nextCursorMark = "AoE="
        mock_solr.search.return_value = raw
        backend._clients["products"] = mock_solr

        result = backend.search("products", "shoes", cursorMark="*", sort=["-score"])

        kwargs = mock_solr.search.call_args[1]
        assert kwargs["cursorMark"] == "*"
        assert "nextCursorMark" in result
        assert result["nextCursorMark"] == "AoE="

    def test_cursor_mark_appends_id_asc_when_sort_missing_id(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results()
        backend._clients["products"] = mock_solr

        backend.search("products", "shoes", cursorMark="*", sort=["-score"])

        kwargs = mock_solr.search.call_args[1]
        assert "id asc" in kwargs["sort"]

    def test_qf_set_from_searchable_attrs_cache(self) -> None:
        backend = _make_backend()
        backend._searchable_attrs["products"] = ["title^3", "description"]
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results()
        backend._clients["products"] = mock_solr

        backend.search("products", "shoes")

        kwargs = mock_solr.search.call_args[1]
        assert "qf" in kwargs
        assert "title^3" in kwargs["qf"]


# ---------------------------------------------------------------------------
# Response normalisation
# ---------------------------------------------------------------------------


class TestNormaliseSearchResponse:
    def test_response_includes_canonical_keys(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results(docs=[{"id": "1", "title": "Shoe"}], hits=1, qtime=3)
        backend._clients["products"] = mock_solr

        result = backend.search("products", "shoe")

        assert "hits" in result
        assert "estimatedTotalHits" in result
        assert "processingTimeMs" in result
        assert "limit" in result
        assert "offset" in result
        assert "facetDistribution" in result
        assert "formattedHits" in result

    def test_hits_contain_docs(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results(docs=[{"id": "1", "title": "Shoe"}], hits=1)
        backend._clients["products"] = mock_solr

        result = backend.search("products", "shoe")

        assert result["hits"] == [{"id": "1", "title": "Shoe"}]
        assert result["estimatedTotalHits"] == 1

    def test_highlighting_merged_into_formatted_hits(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results(
            docs=[{"id": "doc-1", "title": "Running Shoes"}],
            highlighting={"doc-1": {"title": ["Running <em>Shoes</em>"]}},
        )
        backend._clients["products"] = mock_solr

        result = backend.search("products", "shoes", attributesToHighlight=["title"])

        formatted = result["formattedHits"]
        assert formatted[0]["title"] == "Running <em>Shoes</em>"

    def test_facet_distribution_normalised(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results(
            facets={
                "category": {
                    "buckets": [
                        {"val": "electronics", "count": 42},
                        {"val": "clothing", "count": 18},
                    ]
                }
            }
        )
        backend._clients["products"] = mock_solr

        result = backend.search("products", "item", facets=["category"])

        assert result["facetDistribution"]["category"]["electronics"] == 42
        assert result["facetDistribution"]["category"]["clothing"] == 18


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


class TestErrorMapping:
    def test_solr_error_maps_to_search_backend_error(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.side_effect = pysolr.SolrError("Bad query")
        backend._clients["products"] = mock_solr

        with pytest.raises(SearchBackendError, match="Solr error"):
            backend.search("products", "bad query")

    def test_timeout_solr_error_maps_to_search_timeout_error(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.side_effect = pysolr.SolrError("Connection timed out")
        backend._clients["products"] = mock_solr

        with pytest.raises(SearchTimeoutError):
            backend.search("products", "shoes")

    def test_admin_404_maps_to_index_not_found_error(self) -> None:
        backend = _make_backend()
        backend._http.request.return_value = _http_response(404)

        with pytest.raises(IndexNotFoundError):
            backend.get_stats("missing_collection")

    def test_admin_500_maps_to_search_backend_error(self) -> None:
        backend = _make_backend()
        backend._http.request.return_value = _http_response(500, {"error": "server error"})

        with pytest.raises(SearchBackendError):
            backend.get_stats("products")


# ---------------------------------------------------------------------------
# add_documents / delete_documents / clear_documents
# ---------------------------------------------------------------------------


class TestDocumentOperations:
    def test_add_documents_calls_pysolr_add(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        backend._clients["products"] = mock_solr

        docs = [{"id": "1", "title": "Shoe"}]
        result = backend.add_documents("products", docs)

        mock_solr.add.assert_called_once_with(docs, commit=False, commitWithin=backend.commit_within)
        assert result["status"] == "succeeded"
        assert result["indexUid"] == "products"

    def test_delete_documents_calls_pysolr_delete_with_ids(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        backend._clients["products"] = mock_solr

        result = backend.delete_documents("products", ["1", "2"])

        mock_solr.delete.assert_called_once_with(id=["1", "2"], commit=False, commitWithin=backend.commit_within)
        assert result["status"] == "succeeded"

    def test_clear_documents_uses_star_query_with_immediate_commit(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        backend._clients["products"] = mock_solr

        backend.clear_documents("products")

        mock_solr.delete.assert_called_once_with(q="*:*", commit=True)

    def test_update_documents_calls_pysolr_add(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        backend._clients["products"] = mock_solr

        docs = [{"id": "1", "stock_count": {"set": 0}}]
        result = backend.update_documents("products", docs)

        mock_solr.add.assert_called_once()
        assert result["status"] == "succeeded"


# ---------------------------------------------------------------------------
# get_document / get_documents
# ---------------------------------------------------------------------------


class TestGetDocument:
    def test_get_document_uses_real_time_get(self) -> None:
        backend = _make_backend()
        backend._http.request.return_value = _http_response(200, {"doc": {"id": "prod-1", "title": "Shoe"}})

        doc = backend.get_document("products", "prod-1")

        call_args = backend._http.request.call_args
        assert "get" in call_args[0][1].lower()
        assert doc["id"] == "prod-1"

    def test_get_document_raises_when_doc_missing(self) -> None:
        backend = _make_backend()
        backend._http.request.return_value = _http_response(200, {"doc": None})

        with pytest.raises(SearchBackendError, match="not found"):
            backend.get_document("products", "missing-id")

    def test_get_documents_with_ids_uses_batch_get(self) -> None:
        backend = _make_backend()
        backend._http.request.return_value = _http_response(200, {"response": {"docs": [{"id": "1"}, {"id": "2"}]}})

        result = backend.get_documents("products", document_ids=["1", "2"])

        assert len(result) == 2

    def test_get_documents_browse_mode_uses_search(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results(docs=[{"id": "1"}, {"id": "2"}], hits=2)
        backend._clients["products"] = mock_solr

        result = backend.get_documents("products", limit=2, offset=0)

        mock_solr.search.assert_called_once()
        assert len(result) == 2


# ---------------------------------------------------------------------------
# facet_search
# ---------------------------------------------------------------------------


class TestFacetSearch:
    def test_facet_search_passes_prefix_parameter(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results(
            facets={
                "category": {
                    "buckets": [
                        {"val": "electronics", "count": 10},
                        {"val": "electrics", "count": 5},
                    ]
                }
            }
        )
        backend._clients["products"] = mock_solr

        backend.facet_search("products", "category", "ele")

        kwargs = mock_solr.search.call_args[1]
        facet_def = json.loads(kwargs["json.facet"])
        assert facet_def["category"]["prefix"] == "ele"

    def test_facet_search_returns_sorted_by_count_desc(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results(
            facets={
                "category": {
                    "buckets": [
                        {"val": "electrics", "count": 5},
                        {"val": "electronics", "count": 10},
                    ]
                }
            }
        )
        backend._clients["products"] = mock_solr

        result = backend.facet_search("products", "category", "ele")

        assert result[0]["count"] >= result[1]["count"]

    def test_facet_search_no_prefix_when_empty_query(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.search.return_value = _solr_results(facets={"category": {"buckets": []}})
        backend._clients["products"] = mock_solr

        backend.facet_search("products", "category")

        kwargs = mock_solr.search.call_args[1]
        facet_def = json.loads(kwargs["json.facet"])
        assert "prefix" not in facet_def["category"]


# ---------------------------------------------------------------------------
# similar_documents
# ---------------------------------------------------------------------------


class TestSimilarDocuments:
    def test_similar_documents_uses_more_like_this(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.more_like_this.return_value = _solr_results(docs=[{"id": "prod-2", "title": "Boot"}], hits=1)
        backend._clients["products"] = mock_solr
        backend._searchable_attrs["products"] = ["title", "description"]

        result = backend.similar_documents("products", "prod-1")

        mock_solr.more_like_this.assert_called_once()
        call_args = mock_solr.more_like_this.call_args
        assert call_args[1]["q"] == "id:prod-1"
        assert "title" in call_args[1]["mltfl"]
        assert "hits" in result

    def test_similar_documents_mlt_fields_override(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.more_like_this.return_value = _solr_results()
        backend._clients["products"] = mock_solr

        backend.similar_documents("products", "prod-1", mlt_fields="custom_field")

        kwargs = mock_solr.more_like_this.call_args[1]
        assert kwargs["mltfl"] == "custom_field"

    def test_boost_weights_stripped_from_searchable_attrs(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.more_like_this.return_value = _solr_results()
        backend._clients["products"] = mock_solr
        backend._searchable_attrs["products"] = ["title^3", "description^1"]

        backend.similar_documents("products", "prod-1")

        kwargs = mock_solr.more_like_this.call_args[1]
        assert "^" not in kwargs["mltfl"]


# ---------------------------------------------------------------------------
# compact
# ---------------------------------------------------------------------------


class TestCompact:
    def test_compact_calls_optimize(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.optimize.return_value = {"responseHeader": {"status": 0}}
        backend._clients["products"] = mock_solr

        result = backend.compact("products")

        mock_solr.optimize.assert_called_once()
        assert isinstance(result, dict)

    def test_compact_never_raises(self) -> None:
        backend = _make_backend()
        mock_solr = MagicMock()
        mock_solr.optimize.side_effect = pysolr.SolrError("optimize failed")
        backend._clients["products"] = mock_solr

        result = backend.compact("products")  # Must not raise.

        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# swap_indexes
# ---------------------------------------------------------------------------


class TestSwapIndexes:
    def test_swap_indexes_issues_createalias_for_each_direction(self) -> None:
        backend = _make_backend()
        backend._http.request.return_value = _http_response(200, {"responseHeader": {"status": 0}})

        backend.swap_indexes([("index_a", "index_b")])

        assert backend._http.request.call_count == 2
        all_calls = backend._http.request.call_args_list
        params_list = [c[1]["params"]["action"] for c in all_calls]
        assert all(p == "CREATEALIAS" for p in params_list)

    def test_swap_response_contains_swaps_key(self) -> None:
        backend = _make_backend()
        backend._http.request.return_value = _http_response(200, {})

        result = backend.swap_indexes([("a", "b")])

        assert "swaps" in result
        assert len(result["swaps"]) == 1


# ---------------------------------------------------------------------------
# get_task
# ---------------------------------------------------------------------------


class TestGetTask:
    def test_get_task_returns_succeeded_immediately(self) -> None:
        backend = _make_backend()
        result = backend.get_task("any-uid")
        assert result["status"] == "succeeded"
        assert result["taskUid"] == "any-uid"


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_returns_true_when_solr_responds(self) -> None:
        backend = _make_backend()
        backend._http.request.return_value = _http_response(200, {"lucene": {}})

        assert backend.health() is True

    def test_returns_false_on_backend_error(self) -> None:
        backend = _make_backend()
        backend._http.request.return_value = _http_response(500, {"error": "oops"})

        assert backend.health() is False

    def test_returns_false_on_timeout(self) -> None:
        import httpx

        backend = _make_backend()
        backend._http.request.side_effect = httpx.TimeoutException("timeout")

        assert backend.health() is False

    def test_solrcloud_also_checks_cluster_endpoint(self) -> None:
        backend = _make_backend(zookeeper_hosts="zoo1:2181")
        backend._http.request.return_value = _http_response(200, {})

        backend.health()

        call_paths = [c[0][1] for c in backend._http.request.call_args_list]
        assert any("cluster" in p for p in call_paths)
