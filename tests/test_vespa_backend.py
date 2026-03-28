"""Tests for the Vespa search backend.

All tests in this module are skipped when ``pyvespa`` is not installed.
Vespa operations are fully mocked — no live Vespa instance is required.
"""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Skip guard — all tests require pyvespa to be importable.
# ---------------------------------------------------------------------------

pyvespa_available = importlib.util.find_spec("vespa") is not None
pytestmark = pytest.mark.skipif(
    not pyvespa_available,
    reason="pyvespa not installed — skipping Vespa backend tests",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

if pyvespa_available:
    from django.core.exceptions import ImproperlyConfigured

    from icv_search.backends.vespa import (
        VespaBackend,
        _normalise_hits,
        translate_filter_to_yql,
        translate_sort_to_yql,
    )
    from icv_search.exceptions import (
        IndexNotFoundError,
        SearchBackendError,
        SearchTimeoutError,
    )


def _make_backend(**kwargs: Any) -> VespaBackend:
    """Construct a VespaBackend with a mocked pyvespa client."""
    defaults = dict(url="http://localhost:8080", api_key="", schema="product")
    defaults.update(kwargs)
    with patch("icv_search.backends.vespa.VespaApp"):
        backend = VespaBackend(**defaults)
    backend._app = MagicMock()
    return backend


# ---------------------------------------------------------------------------
# 1. Import guard — ImproperlyConfigured when pyvespa absent
# ---------------------------------------------------------------------------


def test_import_guard_raises_when_pyvespa_missing() -> None:
    """__init__ raises ImproperlyConfigured when pyvespa is not installed."""
    with (
        patch("icv_search.backends.vespa._pyvespa_available", False),
        pytest.raises(ImproperlyConfigured, match="pyvespa is required"),
    ):
        VespaBackend(url="http://localhost:8080", api_key="")


# ---------------------------------------------------------------------------
# 2. Constructor — kwargs extracted correctly
# ---------------------------------------------------------------------------


def test_constructor_extracts_vespa_kwargs() -> None:
    """Constructor stores Vespa-specific kwargs on the instance."""
    backend = _make_backend(
        application="my-app",
        content_cluster="my-cluster",
        schema="article",
        cert_path="/tmp/cert.pem",
        key_path="/tmp/key.pem",
    )
    assert backend.application == "my-app"
    assert backend.content_cluster == "my-cluster"
    assert backend.schema == "article"


def test_constructor_defaults() -> None:
    """Constructor uses sensible defaults for optional Vespa kwargs."""
    backend = _make_backend()
    assert backend.content_cluster == "content"
    assert backend.application == ""


# ---------------------------------------------------------------------------
# 3. YQL filter translation
# ---------------------------------------------------------------------------


def test_translate_filter_string_rejected() -> None:
    """Raw YQL strings are rejected to prevent injection."""
    from icv_search.exceptions import SearchBackendError

    raw = 'nearestNeighbor(embedding, query_embedding) AND category contains "shoes"'
    with pytest.raises(SearchBackendError, match="does not accept raw YQL filter strings"):
        translate_filter_to_yql(raw)


def test_translate_filter_empty_dict() -> None:
    assert translate_filter_to_yql({}) == ""


def test_translate_filter_string_value() -> None:
    result = translate_filter_to_yql({"category": "shoes"})
    assert result == 'category contains "shoes"'


def test_translate_filter_int_value() -> None:
    result = translate_filter_to_yql({"count": 5})
    assert result == "count = 5"


def test_translate_filter_float_value() -> None:
    result = translate_filter_to_yql({"price": 12.99})
    assert result == "price = 12.99"


def test_translate_filter_bool_true() -> None:
    assert translate_filter_to_yql({"is_active": True}) == "is_active = true"


def test_translate_filter_bool_false() -> None:
    assert translate_filter_to_yql({"is_active": False}) == "is_active = false"


def test_translate_filter_none_value() -> None:
    assert translate_filter_to_yql({"status": None}) == "!(status)"


def test_translate_filter_list_value() -> None:
    result = translate_filter_to_yql({"category": ["shoes", "boots"]})
    assert result == 'category in ["shoes", "boots"]'


def test_translate_filter_gte() -> None:
    assert translate_filter_to_yql({"price__gte": 20}) == "price >= 20"


def test_translate_filter_lte() -> None:
    assert translate_filter_to_yql({"price__lte": 100}) == "price <= 100"


def test_translate_filter_gt() -> None:
    assert translate_filter_to_yql({"price__gt": 0}) == "price > 0"


def test_translate_filter_lt() -> None:
    assert translate_filter_to_yql({"price__lt": 50}) == "price < 50"


def test_translate_filter_multiple_conditions() -> None:
    """Multiple conditions are joined with AND."""
    result = translate_filter_to_yql({"category": "shoes", "is_active": True})
    assert "AND" in result
    assert 'category contains "shoes"' in result
    assert "is_active = true" in result


# ---------------------------------------------------------------------------
# 4. YQL sort translation
# ---------------------------------------------------------------------------


def test_translate_sort_empty() -> None:
    assert translate_sort_to_yql([]) == ""


def test_translate_sort_ascending() -> None:
    assert translate_sort_to_yql(["price"]) == "price asc"


def test_translate_sort_descending() -> None:
    assert translate_sort_to_yql(["-price"]) == "price desc"


def test_translate_sort_multiple() -> None:
    assert translate_sort_to_yql(["price", "-created_at"]) == "price asc, created_at desc"


def test_translate_sort_string_passthrough() -> None:
    raw = "price desc"
    assert translate_sort_to_yql(raw) == raw


# ---------------------------------------------------------------------------
# 5. create_index — connectivity check and local registry
# ---------------------------------------------------------------------------


def test_create_index_returns_succeeded() -> None:
    backend = _make_backend()
    backend._app.get_application_status.return_value = MagicMock()
    backend._app.query.return_value = MagicMock(status_code=200)

    result = backend.create_index("products")

    assert result["status"] == "succeeded"
    assert result["indexUid"] == "products"
    assert "products" in backend._index_registry


def test_create_index_raises_on_connectivity_failure() -> None:
    backend = _make_backend()
    backend._app.get_application_status.side_effect = RuntimeError("connection refused")

    with pytest.raises(SearchBackendError, match="connectivity check failed"):
        backend.create_index("products")


def test_create_index_logs_warning_when_schema_missing(caplog: Any) -> None:
    """A warning is logged when the schema is not visible in Vespa."""
    backend = _make_backend()
    backend._app.get_application_status.return_value = MagicMock()
    backend._app.query.side_effect = RuntimeError("schema not found")

    import logging

    with caplog.at_level(logging.WARNING, logger="icv_search.backends.vespa"):
        backend.create_index("nonexistent_schema")

    assert any("vespa deploy" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# 6. update_settings — stores locally, logs warning, no network call
# ---------------------------------------------------------------------------


def test_update_settings_stores_locally_and_warns(caplog: Any) -> None:
    import logging

    backend = _make_backend()
    settings = {"searchableAttributes": ["title"], "filterableAttributes": ["price"]}

    with caplog.at_level(logging.WARNING, logger="icv_search.backends.vespa"):
        result = backend.update_settings("products", settings)

    assert result["status"] == "succeeded"
    assert backend._settings_registry["products"] == settings
    backend._app.assert_not_called()
    assert any("vespa deploy" in r.message.lower() for r in caplog.records)


def test_get_settings_returns_stored() -> None:
    backend = _make_backend()
    settings = {"searchableAttributes": ["title"]}
    backend._settings_registry["products"] = settings
    assert backend.get_settings("products") == settings


def test_get_settings_returns_empty_when_not_set() -> None:
    backend = _make_backend()
    assert backend.get_settings("nonexistent") == {}


# ---------------------------------------------------------------------------
# 7. add_documents — feeds via pyvespa feed_batch
# ---------------------------------------------------------------------------


def test_add_documents_calls_feed_batch() -> None:
    backend = _make_backend(schema="product")
    docs = [{"id": "1", "title": "Widget"}, {"id": "2", "title": "Gadget"}]

    result = backend.add_documents("product", docs)

    assert result["status"] == "succeeded"
    assert result["documentCount"] == 2
    backend._app.feed_batch.assert_called_once()


def test_add_documents_raises_on_timeout() -> None:
    backend = _make_backend()
    backend._app.feed_batch.side_effect = RuntimeError("connection timed out")

    with pytest.raises(SearchTimeoutError):
        backend.add_documents("products", [{"id": "1"}])


def test_add_documents_raises_on_backend_error() -> None:
    backend = _make_backend()
    backend._app.feed_batch.side_effect = RuntimeError("unexpected error")

    with pytest.raises(SearchBackendError):
        backend.add_documents("products", [{"id": "1"}])


# ---------------------------------------------------------------------------
# 8. delete_documents — calls delete_data per document
# ---------------------------------------------------------------------------


def test_delete_documents_calls_delete_data_for_each() -> None:
    backend = _make_backend()
    mock_response = MagicMock(status_code=200)
    backend._app.delete_data.return_value = mock_response

    result = backend.delete_documents("products", ["1", "2", "3"])

    assert result["status"] == "succeeded"
    assert backend._app.delete_data.call_count == 3


def test_delete_documents_ignores_404() -> None:
    """A 404 (document already absent) is treated as success."""
    backend = _make_backend()
    backend._app.delete_data.side_effect = RuntimeError("404 not found")

    result = backend.delete_documents("products", ["missing-doc"])
    assert result["status"] == "succeeded"


# ---------------------------------------------------------------------------
# 9. search — YQL construction and ranking profile pass-through
# ---------------------------------------------------------------------------


def _mock_search_response(hits: list[dict[str, Any]], total: int = 0) -> MagicMock:
    """Build a mock VespaQueryResponse."""
    mock = MagicMock()
    mock.status_code = 200
    mock.json = {
        "root": {
            "fields": {"totalCount": total},
            "children": [
                {
                    "id": "toplevel",
                    "children": hits,
                }
            ],
        },
        "timing": {"querytime": 0.012},
    }
    mock.hits = hits
    return mock


def test_search_builds_yql_with_userquery() -> None:
    backend = _make_backend(schema="product")
    backend._app.query.return_value = _mock_search_response([])

    backend.search("product", "running shoes")

    call_kwargs = backend._app.query.call_args[1]
    yql = call_kwargs["body"]["yql"]
    assert "userQuery()" in yql
    assert "product" in yql


def test_search_applies_filter() -> None:
    backend = _make_backend(schema="product")
    backend._app.query.return_value = _mock_search_response([])

    backend.search("product", "shoes", filter={"is_active": True})

    call_kwargs = backend._app.query.call_args[1]
    yql = call_kwargs["body"]["yql"]
    assert "is_active = true" in yql


def test_search_applies_sort_order_by() -> None:
    backend = _make_backend(schema="product")
    backend._app.query.return_value = _mock_search_response([])

    backend.search("product", "shoes", sort=["-price"])

    call_kwargs = backend._app.query.call_args[1]
    yql = call_kwargs["body"]["yql"]
    assert "order by" in yql.lower()
    assert "price desc" in yql


def test_search_passes_ranking_profile() -> None:
    backend = _make_backend(schema="product")
    backend._app.query.return_value = _mock_search_response([])

    backend.search("product", "shoes", ranking="bm25")

    call_kwargs = backend._app.query.call_args[1]
    assert call_kwargs["body"]["ranking"] == "bm25"


def test_search_passes_ranking_features() -> None:
    backend = _make_backend(schema="product")
    backend._app.query.return_value = _mock_search_response([])
    features = {"query(embedding)": [0.1, 0.2, 0.3]}

    backend.search("product", "shoes", **{"ranking.features": features})

    call_kwargs = backend._app.query.call_args[1]
    assert call_kwargs["body"]["ranking.features"] == features


def test_search_attributes_to_retrieve_in_yql() -> None:
    backend = _make_backend(schema="product")
    backend._app.query.return_value = _mock_search_response([])

    backend.search("product", "shoes", attributesToRetrieve=["title", "price"])

    call_kwargs = backend._app.query.call_args[1]
    yql = call_kwargs["body"]["yql"]
    assert "id" in yql  # BR-010 — id always included
    assert "title" in yql
    assert "price" in yql


def test_search_highlight_sets_bolding() -> None:
    backend = _make_backend(schema="product")
    backend._app.query.return_value = _mock_search_response([])

    backend.search("product", "shoes", highlight=True)

    call_kwargs = backend._app.query.call_args[1]
    assert call_kwargs["body"]["presentation.bolding"] is True
    assert call_kwargs["body"]["summary"] == "dynamic"


def test_search_normalises_hits() -> None:
    raw_hits = [
        {
            "id": "id:product:product::42",
            "relevance": 0.876,
            "fields": {"title": "Widget", "price": 9.99},
        }
    ]
    backend = _make_backend(schema="product")
    backend._app.query.return_value = _mock_search_response(raw_hits, total=1)

    result = backend.search("product", "widget")

    assert len(result["hits"]) == 1
    hit = result["hits"][0]
    assert hit["id"] == "42"
    assert hit["title"] == "Widget"
    assert hit["_relevance"] == pytest.approx(0.876)


def test_search_raises_timeout() -> None:
    backend = _make_backend()
    backend._app.query.side_effect = RuntimeError("request timed out")

    with pytest.raises(SearchTimeoutError):
        backend.search("products", "shoes")


def test_search_raises_backend_error() -> None:
    backend = _make_backend()
    backend._app.query.side_effect = RuntimeError("unexpected server error")

    with pytest.raises(SearchBackendError):
        backend.search("products", "shoes")


# ---------------------------------------------------------------------------
# 10. get_stats
# ---------------------------------------------------------------------------


def test_get_stats_returns_document_count() -> None:
    backend = _make_backend(schema="product")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = {"root": {"fields": {"totalCount": 9876}}}
    backend._app.query.return_value = mock_response

    stats = backend.get_stats("product")

    assert stats["document_count"] == 9876
    assert stats["is_indexing"] is False


# ---------------------------------------------------------------------------
# 11. health
# ---------------------------------------------------------------------------


def test_health_returns_true_when_vespa_reachable() -> None:
    backend = _make_backend()
    backend._app.get_application_status.return_value = MagicMock()
    assert backend.health() is True


def test_health_returns_false_on_error() -> None:
    backend = _make_backend()
    backend._app.get_application_status.side_effect = RuntimeError("unreachable")
    assert backend.health() is False


# ---------------------------------------------------------------------------
# 12. get_task — synchronous no-op
# ---------------------------------------------------------------------------


def test_get_task_returns_succeeded() -> None:
    backend = _make_backend()
    result = backend.get_task("vespa-add-products-50")
    assert result["status"] == "succeeded"
    assert result["uid"] == "vespa-add-products-50"


# ---------------------------------------------------------------------------
# 13. swap_indexes — raises NotImplementedError
# ---------------------------------------------------------------------------


def test_swap_indexes_raises_not_implemented() -> None:
    backend = _make_backend()
    with pytest.raises(NotImplementedError, match="vespa deploy"):
        backend.swap_indexes([("idx_a", "idx_b")])


# ---------------------------------------------------------------------------
# 14. get_document
# ---------------------------------------------------------------------------


def test_get_document_returns_fields_with_id() -> None:
    backend = _make_backend(schema="product")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.get_json.return_value = {
        "fields": {"title": "Widget", "price": 9.99},
    }
    backend._app.get_data.return_value = mock_response

    doc = backend.get_document("product", "42")

    assert doc["id"] == "42"  # BR-012
    assert doc["title"] == "Widget"
    assert doc["price"] == 9.99


def test_get_document_raises_index_not_found_on_404() -> None:
    backend = _make_backend(schema="product")
    backend._app.get_data.side_effect = RuntimeError("404 not found")

    with pytest.raises(IndexNotFoundError):
        backend.get_document("product", "missing-id")


# ---------------------------------------------------------------------------
# 15. update_documents — partial update via assign operator
# ---------------------------------------------------------------------------


def test_update_documents_uses_assign_operator() -> None:
    backend = _make_backend(schema="product")
    mock_response = MagicMock(status_code=200)
    backend._app.update_data.return_value = mock_response

    docs = [{"id": "1", "price": 14.99}, {"id": "2", "price": 19.99}]
    result = backend.update_documents("product", docs)

    assert result["status"] == "succeeded"
    assert backend._app.update_data.call_count == 2

    # Verify assign operator is used for fields.
    first_call_kwargs = backend._app.update_data.call_args_list[0][1]
    assert first_call_kwargs["fields"]["price"] == {"assign": 14.99}
    assert "id" not in first_call_kwargs["fields"]  # Primary key excluded.


def test_update_documents_raises_on_error() -> None:
    backend = _make_backend()
    backend._app.update_data.side_effect = RuntimeError("vespa error")

    with pytest.raises(SearchBackendError, match="update_documents errors"):
        backend.update_documents("products", [{"id": "1", "title": "New"}])


# ---------------------------------------------------------------------------
# 16. facet_search — raises NotImplementedError
# ---------------------------------------------------------------------------


def test_facet_search_raises_not_implemented() -> None:
    backend = _make_backend()
    with pytest.raises(NotImplementedError, match="facet_search"):
        backend.facet_search("products", "category")


# ---------------------------------------------------------------------------
# 17. similar_documents — raises NotImplementedError
# ---------------------------------------------------------------------------


def test_similar_documents_raises_not_implemented() -> None:
    backend = _make_backend()
    with pytest.raises(NotImplementedError, match="similar_documents"):
        backend.similar_documents("products", "doc-42")


# ---------------------------------------------------------------------------
# 18. compact — no-op
# ---------------------------------------------------------------------------


def test_compact_returns_empty_dict() -> None:
    backend = _make_backend()
    assert backend.compact("products") == {}
    backend._app.assert_not_called()


# ---------------------------------------------------------------------------
# 19. Error mapping — HTTP status code to exception type
# ---------------------------------------------------------------------------


def test_check_response_408_raises_timeout() -> None:
    backend = _make_backend()
    mock_response = MagicMock(status_code=408)
    with pytest.raises(SearchTimeoutError):
        backend._check_response(mock_response, context="test 408")


def test_check_response_503_raises_timeout() -> None:
    backend = _make_backend()
    mock_response = MagicMock(status_code=503)
    with pytest.raises(SearchTimeoutError):
        backend._check_response(mock_response, context="test 503")


def test_check_response_404_raises_index_not_found() -> None:
    backend = _make_backend()
    mock_response = MagicMock(status_code=404)
    with pytest.raises(IndexNotFoundError):
        backend._check_response(mock_response, context="test 404")


def test_check_response_500_raises_backend_error() -> None:
    backend = _make_backend()
    mock_response = MagicMock(status_code=500)
    with pytest.raises(SearchBackendError):
        backend._check_response(mock_response, context="test 500")


def test_check_response_200_is_noop() -> None:
    backend = _make_backend()
    mock_response = MagicMock(status_code=200)
    # Should not raise.
    backend._check_response(mock_response, context="test 200")


def test_check_response_none_is_noop() -> None:
    backend = _make_backend()
    backend._check_response(None)  # Should not raise.


# ---------------------------------------------------------------------------
# 20. _normalise_hits — hit flattening
# ---------------------------------------------------------------------------


def test_normalise_hits_extracts_short_id() -> None:
    raw = [{"id": "id:products:products::99", "relevance": 0.5, "fields": {"title": "X"}}]
    hits = _normalise_hits(raw)
    assert hits[0]["id"] == "99"


def test_normalise_hits_preserves_fields() -> None:
    raw = [{"id": "id:products:products::1", "relevance": 0.9, "fields": {"price": 10.0}}]
    hits = _normalise_hits(raw)
    assert hits[0]["price"] == 10.0
    assert hits[0]["_relevance"] == pytest.approx(0.9)


def test_normalise_hits_empty_list() -> None:
    assert _normalise_hits([]) == []


# ---------------------------------------------------------------------------
# 21. clear_documents
# ---------------------------------------------------------------------------


def test_clear_documents_calls_delete_all_docs() -> None:
    backend = _make_backend(schema="product", content_cluster="my_cluster")
    backend._app.delete_all_docs.return_value = None

    result = backend.clear_documents("product")

    assert result["status"] == "succeeded"
    backend._app.delete_all_docs.assert_called_once_with(
        content_cluster_name="my_cluster",
        schema="product",
    )


# ---------------------------------------------------------------------------
# 22. delete_index — clears registry entry
# ---------------------------------------------------------------------------


def test_delete_index_removes_from_registry() -> None:
    backend = _make_backend(schema="product")
    backend._index_registry["products"] = {"primary_key": "id"}
    backend._settings_registry["products"] = {}
    backend._app.delete_all_docs.return_value = None

    backend.delete_index("products")

    assert "products" not in backend._index_registry
    assert "products" not in backend._settings_registry


# ---------------------------------------------------------------------------
# 23. multi_search uses base class (loop over search)
# ---------------------------------------------------------------------------


def test_multi_search_delegates_to_search() -> None:
    """multi_search uses the base class default loop — not overridden."""
    backend = _make_backend(schema="product")
    backend._app.query.return_value = _mock_search_response([])

    queries = [
        {"uid": "product", "query": "shoes"},
        {"uid": "product", "query": "boots"},
    ]
    results = backend.multi_search(queries)

    assert len(results) == 2
    assert backend._app.query.call_count == 2
