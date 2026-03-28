"""Tests for search backends: DummyBackend and MeilisearchBackend."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from icv_search.backends.dummy import DummyBackend, _documents, _indexes, _settings
from icv_search.backends.meilisearch import MeilisearchBackend
from icv_search.exceptions import IndexNotFoundError, SearchBackendError, SearchTimeoutError


class TestDummyBackendCreate:
    """DummyBackend index creation."""

    def test_create_index_stores_index(self):
        backend = DummyBackend()
        backend.create_index("products")
        assert "products" in _indexes

    def test_create_index_returns_uid(self):
        backend = DummyBackend()
        result = backend.create_index("orders", primary_key="order_id")
        assert result["uid"] == "orders"
        assert result["primaryKey"] == "order_id"

    def test_create_index_initialises_document_store(self):
        backend = DummyBackend()
        backend.create_index("docs")
        assert _documents["docs"] == {}

    def test_create_index_initialises_settings_store(self):
        backend = DummyBackend()
        backend.create_index("docs")
        assert _settings["docs"] == {}


class TestDummyBackendDocuments:
    """DummyBackend document operations."""

    def test_add_documents_stores_by_id(self):
        backend = DummyBackend()
        backend.create_index("products")
        docs = [{"id": "1", "name": "Widget"}, {"id": "2", "name": "Gadget"}]
        backend.add_documents("products", docs)
        assert "1" in _documents["products"]
        assert "2" in _documents["products"]

    def test_add_documents_returns_task_uid(self):
        backend = DummyBackend()
        backend.create_index("products")
        result = backend.add_documents("products", [{"id": "1", "name": "Widget"}])
        assert "taskUid" in result
        assert "indexUid" in result

    def test_add_documents_updates_existing(self):
        backend = DummyBackend()
        backend.create_index("products")
        backend.add_documents("products", [{"id": "1", "name": "Widget"}])
        backend.add_documents("products", [{"id": "1", "name": "Updated Widget"}])
        assert _documents["products"]["1"]["name"] == "Updated Widget"

    def test_add_documents_creates_index_if_missing(self):
        backend = DummyBackend()
        # No create_index call
        backend.add_documents("auto-created", [{"id": "1", "name": "test"}])
        assert "1" in _documents["auto-created"]

    def test_delete_documents_removes_by_id(self):
        backend = DummyBackend()
        backend.create_index("products")
        backend.add_documents("products", [{"id": "1", "name": "Widget"}, {"id": "2", "name": "Gadget"}])
        backend.delete_documents("products", ["1"])
        assert "1" not in _documents["products"]
        assert "2" in _documents["products"]

    def test_delete_documents_ignores_missing_ids(self):
        backend = DummyBackend()
        backend.create_index("products")
        # Should not raise
        backend.delete_documents("products", ["nonexistent"])

    def test_delete_documents_returns_task_uid(self):
        backend = DummyBackend()
        backend.create_index("products")
        result = backend.delete_documents("products", ["1"])
        assert "taskUid" in result


class TestDummyBackendSearch:
    """DummyBackend search functionality."""

    def setup_method(self):
        DummyBackend.reset()
        self.backend = DummyBackend()
        self.backend.create_index("articles")
        self.backend.add_documents(
            "articles",
            [
                {"id": "1", "title": "Django REST Framework Guide"},
                {"id": "2", "title": "Python Testing Best Practices"},
                {"id": "3", "title": "Advanced Django Patterns"},
            ],
        )

    def test_search_returns_all_on_empty_query(self):
        result = self.backend.search("articles", "")
        assert len(result["hits"]) == 3

    def test_search_filters_by_query(self):
        result = self.backend.search("articles", "Django")
        titles = [h["title"] for h in result["hits"]]
        assert all("Django" in t for t in titles)
        assert len(result["hits"]) == 2

    def test_search_case_insensitive(self):
        result = self.backend.search("articles", "django")
        assert len(result["hits"]) == 2

    def test_search_returns_query_in_response(self):
        result = self.backend.search("articles", "Python")
        assert result["query"] == "Python"

    def test_search_returns_estimated_total_hits(self):
        result = self.backend.search("articles", "")
        assert "estimatedTotalHits" in result
        assert result["estimatedTotalHits"] == 3

    def test_search_respects_limit(self):
        result = self.backend.search("articles", "", limit=2)
        assert len(result["hits"]) == 2

    def test_search_respects_offset(self):
        result_all = self.backend.search("articles", "", limit=100)
        result_offset = self.backend.search("articles", "", offset=1, limit=100)
        assert len(result_offset["hits"]) == len(result_all["hits"]) - 1

    def test_search_empty_index_returns_empty_hits(self):
        self.backend.create_index("empty")
        result = self.backend.search("empty", "anything")
        assert result["hits"] == []


class TestDummyBackendMiscOps:
    """DummyBackend: delete_index, get_stats, health, get_task."""

    def test_delete_index_removes_index(self):
        backend = DummyBackend()
        backend.create_index("temp")
        backend.delete_index("temp")
        assert "temp" not in _indexes
        assert "temp" not in _documents

    def test_delete_index_noop_for_missing(self):
        backend = DummyBackend()
        # Should not raise
        backend.delete_index("nonexistent")

    def test_get_stats_returns_document_count(self):
        backend = DummyBackend()
        backend.create_index("products")
        backend.add_documents("products", [{"id": "1"}, {"id": "2"}])
        stats = backend.get_stats("products")
        assert stats["numberOfDocuments"] == 2

    def test_health_returns_true(self):
        backend = DummyBackend()
        assert backend.health() is True

    def test_get_task_returns_succeeded(self):
        backend = DummyBackend()
        result = backend.get_task("some-uid")
        assert result["status"] == "succeeded"

    def test_reset_clears_all_state(self):
        backend = DummyBackend()
        backend.create_index("products")
        backend.add_documents("products", [{"id": "1"}])
        DummyBackend.reset()
        assert _indexes == {}
        assert _documents == {}
        assert _settings == {}

    def test_update_settings_stores_settings(self):
        backend = DummyBackend()
        backend.create_index("products")
        backend.update_settings("products", {"searchableAttributes": ["name"]})
        assert _settings["products"]["searchableAttributes"] == ["name"]

    def test_get_settings_returns_copy(self):
        backend = DummyBackend()
        backend.create_index("products")
        backend.update_settings("products", {"searchableAttributes": ["name"]})
        result = backend.get_settings("products")
        result["searchableAttributes"].append("extra")
        assert _settings["products"]["searchableAttributes"] == ["name"]


class TestDummyBackendAttributesToRetrieve:
    """DummyBackend: attributesToRetrieve field filtering (BR-010)."""

    def setup_method(self):
        DummyBackend.reset()
        self.backend = DummyBackend()
        self.backend.create_index("products")
        self.backend.add_documents(
            "products",
            [
                {"id": "1", "name": "Widget", "price": 9.99, "category": "tools"},
                {"id": "2", "name": "Gadget", "price": 19.99, "category": "electronics"},
            ],
        )

    def test_filters_hits_to_requested_attributes(self):
        result = self.backend.search("products", "", attributesToRetrieve=["name"])
        for hit in result["hits"]:
            assert set(hit.keys()) == {"id", "name"}

    def test_id_always_included_even_if_not_listed(self):
        result = self.backend.search("products", "", attributesToRetrieve=["name"])
        for hit in result["hits"]:
            assert "id" in hit

    def test_multiple_attributes_returned(self):
        result = self.backend.search("products", "", attributesToRetrieve=["name", "price"])
        for hit in result["hits"]:
            assert set(hit.keys()) == {"id", "name", "price"}

    def test_unlisted_attributes_excluded(self):
        result = self.backend.search("products", "", attributesToRetrieve=["name"])
        for hit in result["hits"]:
            assert "price" not in hit
            assert "category" not in hit

    def test_no_filter_when_param_absent(self):
        result = self.backend.search("products", "")
        for hit in result["hits"]:
            # All stored fields should be present.
            assert {"id", "name", "price", "category"}.issubset(hit.keys())

    def test_filters_formatted_hits_when_highlighting(self):
        result = self.backend.search(
            "products",
            "Widget",
            attributesToRetrieve=["name"],
            highlight_fields=["name"],
        )
        assert "formatted_hits" in result
        for hit in result["formatted_hits"]:
            assert set(hit.keys()) == {"id", "name"}
            assert "price" not in hit

    def test_id_in_attributes_to_retrieve_not_duplicated(self):
        """Listing 'id' explicitly should not cause duplicate keys or errors."""
        result = self.backend.search("products", "", attributesToRetrieve=["id", "name"])
        for hit in result["hits"]:
            assert set(hit.keys()) == {"id", "name"}


class TestMeilisearchBackend:
    """MeilisearchBackend: HTTP request handling with mocked httpx."""

    def _make_backend(self):
        return MeilisearchBackend(url="http://localhost:7700", api_key="test-key")

    def _mock_response(self, json_data=None, status_code=200):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = json_data or {}
        response.text = str(json_data)
        return response

    def test_create_index_posts_to_indexes(self):
        backend = self._make_backend()
        mock_resp = self._mock_response({"uid": "products", "primaryKey": "id"})
        backend._client.request = MagicMock(return_value=mock_resp)

        result = backend.create_index("products")

        backend._client.request.assert_called_once()
        call_kwargs = backend._client.request.call_args
        assert call_kwargs[0][0] == "POST"
        assert "/indexes" in call_kwargs[0][1]
        assert result["uid"] == "products"

    def test_search_posts_query(self):
        backend = self._make_backend()
        mock_resp = self._mock_response({"hits": [], "query": "django", "estimatedTotalHits": 0})
        backend._client.request = MagicMock(return_value=mock_resp)

        result = backend.search("articles", "django")

        backend._client.request.assert_called_once()
        call_kwargs = backend._client.request.call_args
        assert call_kwargs[0][0] == "POST"
        assert "articles/search" in call_kwargs[0][1]
        assert result["query"] == "django"

    def test_health_returns_true_when_available(self):
        backend = self._make_backend()
        mock_resp = self._mock_response({"status": "available"})
        backend._client.request = MagicMock(return_value=mock_resp)

        assert backend.health() is True

    def test_health_returns_false_when_engine_down(self):
        backend = self._make_backend()
        import httpx

        backend._client.request = MagicMock(side_effect=httpx.ConnectError("refused"))

        assert backend.health() is False

    def test_404_raises_index_not_found(self):
        backend = self._make_backend()
        mock_resp = self._mock_response(status_code=404)
        backend._client.request = MagicMock(return_value=mock_resp)

        with pytest.raises(IndexNotFoundError):
            backend.get_settings("nonexistent")

    def test_400_raises_search_backend_error(self):
        backend = self._make_backend()
        mock_resp = self._mock_response({"error": "bad request"}, status_code=400)
        mock_resp.text = '{"error": "bad request"}'
        backend._client.request = MagicMock(return_value=mock_resp)

        with pytest.raises(SearchBackendError):
            backend.create_index("bad")

    def test_timeout_raises_search_timeout_error(self):
        import httpx

        backend = self._make_backend()
        backend._client.request = MagicMock(side_effect=httpx.TimeoutException("timeout"))

        with pytest.raises(SearchTimeoutError):
            backend.create_index("products")

    def test_delete_index_sends_delete_request(self):
        backend = self._make_backend()
        mock_resp = self._mock_response(status_code=204)
        mock_resp.json.side_effect = Exception("no body")
        backend._client.request = MagicMock(return_value=mock_resp)

        backend.delete_index("products")

        call_args = backend._client.request.call_args
        assert call_args[0][0] == "DELETE"
        assert "products" in call_args[0][1]

    def test_authorization_header_set_when_api_key_provided(self):
        backend = self._make_backend()
        headers = backend._build_headers()
        assert headers["Authorization"] == "Bearer test-key"

    def test_no_authorization_header_without_api_key(self):
        backend = MeilisearchBackend(url="http://localhost:7700", api_key="")
        headers = backend._build_headers()
        assert "Authorization" not in headers

    def test_get_task_fetches_task_status(self):
        backend = self._make_backend()
        mock_resp = self._mock_response({"uid": "42", "status": "succeeded"})
        backend._client.request = MagicMock(return_value=mock_resp)

        result = backend.get_task("42")
        assert result["status"] == "succeeded"
