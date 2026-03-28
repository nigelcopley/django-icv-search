"""Tests for Meilisearch backend error handling."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from icv_search.backends.meilisearch import MeilisearchBackend
from icv_search.exceptions import IndexNotFoundError, SearchBackendError, SearchTimeoutError


@pytest.fixture
def meilisearch_backend():
    """Create a MeilisearchBackend instance for testing."""
    return MeilisearchBackend(url="http://localhost:7700", api_key="test-key", timeout=30)


class TestMeilisearchRequestErrors:
    """Error handling in _request method."""

    def test_raises_timeout_error_on_timeout(self, meilisearch_backend):
        """_request should raise SearchTimeoutError on httpx.TimeoutException."""
        import httpx

        with (
            patch.object(meilisearch_backend._client, "request", side_effect=httpx.TimeoutException("timeout")),
            pytest.raises(SearchTimeoutError, match="timed out"),
        ):
            meilisearch_backend._request("GET", "/test")

    def test_raises_backend_error_on_http_error(self, meilisearch_backend):
        """_request should raise SearchBackendError on httpx.HTTPError."""
        import httpx

        with (
            patch.object(meilisearch_backend._client, "request", side_effect=httpx.HTTPError("connection failed")),
            pytest.raises(SearchBackendError, match="request failed"),
        ):
            meilisearch_backend._request("GET", "/test")

    def test_raises_index_not_found_on_404(self, meilisearch_backend):
        """_request should raise IndexNotFoundError on 404 status."""
        mock_response = Mock()
        mock_response.status_code = 404

        with (
            patch.object(meilisearch_backend._client, "request", return_value=mock_response),
            pytest.raises(IndexNotFoundError, match="not found"),
        ):
            meilisearch_backend._request("GET", "/test")

    def test_raises_backend_error_on_4xx_status(self, meilisearch_backend):
        """_request should raise SearchBackendError on 400-level errors."""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"

        with (
            patch.object(meilisearch_backend._client, "request", return_value=mock_response),
            pytest.raises(SearchBackendError, match="error 400"),
        ):
            meilisearch_backend._request("GET", "/test")

    def test_raises_backend_error_on_5xx_status(self, meilisearch_backend):
        """_request should raise SearchBackendError on 500-level errors."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"

        with (
            patch.object(meilisearch_backend._client, "request", return_value=mock_response),
            pytest.raises(SearchBackendError, match="error 500"),
        ):
            meilisearch_backend._request("GET", "/test")

    def test_returns_empty_dict_on_204(self, meilisearch_backend):
        """_request should return {} on 204 No Content."""
        mock_response = Mock()
        mock_response.status_code = 204

        with patch.object(meilisearch_backend._client, "request", return_value=mock_response):
            result = meilisearch_backend._request("DELETE", "/test")
            assert result == {}

    def test_returns_json_on_success(self, meilisearch_backend):
        """_request should return parsed JSON on successful response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}

        with patch.object(meilisearch_backend._client, "request", return_value=mock_response):
            result = meilisearch_backend._request("GET", "/test")
            assert result == {"status": "ok"}


class TestMeilisearchHealthCheck:
    """health method."""

    def test_returns_true_when_available(self, meilisearch_backend):
        """health should return True when Meilisearch responds with available status."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "available"}

        with patch.object(meilisearch_backend._client, "request", return_value=mock_response):
            assert meilisearch_backend.health() is True

    def test_returns_false_when_status_not_available(self, meilisearch_backend):
        """health should return False when status is not 'available'."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "unavailable"}

        with patch.object(meilisearch_backend._client, "request", return_value=mock_response):
            assert meilisearch_backend.health() is False

    def test_returns_false_on_backend_error(self, meilisearch_backend):
        """health should return False when SearchBackendError is raised."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "error"

        with patch.object(meilisearch_backend._client, "request", return_value=mock_response):
            assert meilisearch_backend.health() is False

    def test_returns_false_on_timeout(self, meilisearch_backend):
        """health should return False when SearchTimeoutError is raised."""
        import httpx

        with patch.object(meilisearch_backend._client, "request", side_effect=httpx.TimeoutException("timeout")):
            assert meilisearch_backend.health() is False


class TestMeilisearchBuildHeaders:
    """_build_headers method."""

    def test_includes_content_type(self):
        """_build_headers should always include Content-Type."""
        backend = MeilisearchBackend(url="http://localhost:7700", api_key="", timeout=30)
        headers = backend._build_headers()
        assert headers["Content-Type"] == "application/json"

    def test_includes_authorization_when_api_key_present(self):
        """_build_headers should include Authorization header when api_key is set."""
        backend = MeilisearchBackend(url="http://localhost:7700", api_key="my-secret-key", timeout=30)
        headers = backend._build_headers()
        assert headers["Authorization"] == "Bearer my-secret-key"

    def test_omits_authorization_when_api_key_empty(self):
        """_build_headers should not include Authorization when api_key is empty."""
        backend = MeilisearchBackend(url="http://localhost:7700", api_key="", timeout=30)
        headers = backend._build_headers()
        assert "Authorization" not in headers
