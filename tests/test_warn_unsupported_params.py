"""Tests for BaseSearchBackend._warn_unsupported_params and its callers."""

from __future__ import annotations

import logging

import pytest

from icv_search.backends.dummy import DummyBackend


@pytest.fixture(autouse=True)
def reset_dummy():
    """Reset DummyBackend in-memory state before each test."""
    DummyBackend.reset()
    yield
    DummyBackend.reset()


class TestWarnUnsupportedParams:
    """Unit tests for _warn_unsupported_params on BaseSearchBackend."""

    def setup_method(self):
        self.backend = DummyBackend()
        self.backend.create_index("test")
        self.backend.add_documents("test", [{"id": "1", "title": "hello"}])

    def test_no_warning_when_no_meili_specific_params(self, caplog):
        """No debug log when only standard params are passed."""
        with caplog.at_level(logging.DEBUG, logger="icv_search.backends.base"):
            self.backend.search("test", "hello", limit=5, filter={"id": "1"})
        assert "does not support search params" not in caplog.text

    def test_warns_for_meili_specific_param(self, caplog):
        """A debug log is emitted when a Meilisearch-specific param is passed."""
        with caplog.at_level(logging.DEBUG, logger="icv_search.backends.base"):
            self.backend.search("test", "hello", crop_fields=["title"])
        assert "DummyBackend does not support search params" in caplog.text
        assert "crop_fields" in caplog.text

    def test_warns_for_multiple_meili_specific_params(self, caplog):
        """All unsupported params appear in the log message, sorted."""
        with caplog.at_level(logging.DEBUG, logger="icv_search.backends.base"):
            self.backend.search("test", "", hybrid={"semanticRatio": 0.5}, vector=[0.1, 0.2])
        assert "hybrid" in caplog.text
        assert "vector" in caplog.text

    def test_warning_uses_debug_level(self, caplog):
        """The log record is at DEBUG level, not WARNING or above."""
        with caplog.at_level(logging.DEBUG, logger="icv_search.backends.base"):
            self.backend.search("test", "", crop_length=20)
        records = [r for r in caplog.records if "does not support search params" in r.message]
        assert records, "Expected at least one matching log record"
        assert all(r.levelno == logging.DEBUG for r in records)

    def test_no_warning_for_non_meili_unknown_params(self, caplog):
        """Params not in _MEILI_SPECIFIC do not trigger the warning."""
        with caplog.at_level(logging.DEBUG, logger="icv_search.backends.base"):
            # 'custom_param' is not in _MEILI_SPECIFIC so no warning should appear.
            self.backend.search("test", "", custom_param="value")
        assert "does not support search params" not in caplog.text

    def test_supported_set_suppresses_warning(self):
        """Params in the supported set are excluded from the warning."""
        backend = DummyBackend()
        backend.create_index("idx")

        logged: list[str] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                if "does not support search params" in record.getMessage():
                    logged.append(record.getMessage())

        handler = CapturingHandler()
        base_logger = logging.getLogger("icv_search.backends.base")
        base_logger.addHandler(handler)
        original_level = base_logger.level
        base_logger.setLevel(logging.DEBUG)

        try:
            # Treat "crop_fields" as supported — should not appear in warnings.
            backend._warn_unsupported_params(
                {"crop_fields": ["title"], "hybrid": {"semanticRatio": 0.5}},
                supported={"crop_fields"},
            )
        finally:
            base_logger.removeHandler(handler)
            base_logger.setLevel(original_level)

        assert logged, "Expected a warning about 'hybrid'"
        assert "crop_fields" not in logged[0]
        assert "hybrid" in logged[0]

    def test_empty_params_no_warning(self, caplog):
        """No warning when params dict is empty."""
        with caplog.at_level(logging.DEBUG, logger="icv_search.backends.base"):
            self.backend._warn_unsupported_params({}, supported=set())
        assert "does not support search params" not in caplog.text


class TestDummyBackendSearchTriggersWarning:
    """Integration: DummyBackend.search() calls _warn_unsupported_params."""

    def setup_method(self):
        DummyBackend.reset()
        self.backend = DummyBackend()
        self.backend.create_index("products")
        self.backend.add_documents("products", [{"id": "1", "name": "Widget"}])

    def test_search_warns_on_page_param(self, caplog):
        """``page`` is a Meilisearch pagination param — DummyBackend should warn."""
        with caplog.at_level(logging.DEBUG, logger="icv_search.backends.base"):
            self.backend.search("products", "", page=1)
        assert "page" in caplog.text

    def test_search_warns_on_hits_per_page_param(self, caplog):
        """``hits_per_page`` is a Meilisearch pagination param — DummyBackend should warn."""
        with caplog.at_level(logging.DEBUG, logger="icv_search.backends.base"):
            self.backend.search("products", "", hits_per_page=10)
        assert "hits_per_page" in caplog.text

    def test_search_result_unaffected_by_unsupported_params(self, caplog):
        """Passing unsupported params does not prevent search returning results."""
        with caplog.at_level(logging.DEBUG, logger="icv_search.backends.base"):
            result = self.backend.search(
                "products",
                "Widget",
                crop_fields=["name"],
                ranking_score_threshold=0.5,
            )
        assert result["estimatedTotalHits"] >= 1
        assert result["hits"][0]["name"] == "Widget"
