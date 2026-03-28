"""Tests for bulk indexing: add_documents_ndjson, bulk_index, bulk=True paths."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from icv_search.backends.dummy import _documents
from icv_search.models import IndexSyncLog, SearchIndex
from icv_search.services.documents import bulk_index, index_model_instances, reindex_zero_downtime
from icv_search.signals import documents_indexed

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def search_index(db):
    return SearchIndex.objects.create(
        name="articles",
        engine_uid="articles",
        primary_key_field="id",
    )


@pytest.fixture()
def backend(settings):
    settings.ICV_SEARCH_BACKEND = "icv_search.backends.dummy.DummyBackend"
    settings.ICV_SEARCH_URL = ""
    settings.ICV_SEARCH_API_KEY = ""

    from icv_search.backends import get_search_backend, reset_search_backend

    reset_search_backend()
    b = get_search_backend()
    b.create_index("articles", primary_key="id")
    yield b
    reset_search_backend()


def _make_docs(n: int) -> list[dict]:
    return [{"id": str(i), "title": f"Product {i}"} for i in range(n)]


# ---------------------------------------------------------------------------
# add_documents_ndjson on DummyBackend
# ---------------------------------------------------------------------------


class TestDummyNdjson:
    def test_stores_documents(self, backend):
        docs = _make_docs(10)
        result = backend.add_documents_ndjson("articles", docs, primary_key="id")
        assert "taskUid" in result
        assert len(_documents["articles"]) == 10

    def test_accepts_generator(self, backend):
        def gen():
            for i in range(5):
                yield {"id": str(i), "title": f"Item {i}"}

        backend.add_documents_ndjson("articles", gen(), primary_key="id")
        assert len(_documents["articles"]) == 5

    def test_upserts_existing(self, backend):
        backend.add_documents_ndjson("articles", [{"id": "1", "title": "v1"}])
        backend.add_documents_ndjson("articles", [{"id": "1", "title": "v2"}])
        assert _documents["articles"]["1"]["title"] == "v2"


# ---------------------------------------------------------------------------
# bulk_index
# ---------------------------------------------------------------------------


class TestBulkIndex:
    def test_indexes_all_documents(self, backend, search_index):
        docs = _make_docs(100)
        total = bulk_index("articles", docs, batch_size=25, concurrency=2)
        assert total == 100
        assert len(_documents["articles"]) == 100

    def test_progress_callback_called(self, backend, search_index):
        calls: list[tuple[int, int]] = []
        docs = _make_docs(50)

        bulk_index(
            "articles",
            docs,
            batch_size=10,
            concurrency=1,
            progress_callback=lambda done, total: calls.append((done, total)),
            total_hint=50,
        )

        assert len(calls) == 5
        assert calls[-1] == (50, 50)
        # Progress should be monotonically increasing.
        assert all(calls[i][0] <= calls[i + 1][0] for i in range(len(calls) - 1))

    def test_accepts_generator(self, backend, search_index):
        def gen():
            for i in range(30):
                yield {"id": str(i), "title": f"Item {i}"}

        total = bulk_index("articles", gen(), batch_size=10, concurrency=1)
        assert total == 30
        assert len(_documents["articles"]) == 30

    def test_empty_iterable(self, backend, search_index):
        total = bulk_index("articles", iter([]), batch_size=10)
        assert total == 0

    def test_uses_ndjson_method(self, backend, search_index):
        """Verify bulk_index calls add_documents_ndjson, not add_documents."""
        with (
            patch.object(backend, "add_documents_ndjson", wraps=backend.add_documents_ndjson) as mock_ndjson,
            patch.object(backend, "add_documents", wraps=backend.add_documents) as mock_json,
        ):
            bulk_index("articles", _make_docs(10), batch_size=5, concurrency=1)
            assert mock_ndjson.call_count == 2
            assert mock_json.call_count == 0


# ---------------------------------------------------------------------------
# index_model_instances(bulk=True)
# ---------------------------------------------------------------------------


class TestIndexModelInstancesBulk:
    @pytest.fixture()
    def article_model(self, backend, search_index):
        """Return the test Article model class."""
        from search_testapp.models import Article

        return Article

    def test_bulk_creates_single_sync_log(self, article_model, db):
        # Create some articles.
        for i in range(10):
            article_model.objects.create(title=f"Article {i}", body=f"Body {i}", author="Author")

        initial_logs = IndexSyncLog.objects.count()
        index_model_instances(article_model, bulk=True, batch_size=3)
        new_logs = IndexSyncLog.objects.count() - initial_logs
        # Bulk path creates exactly 1 summary log (not 1 per batch).
        assert new_logs == 1

    def test_bulk_fires_single_signal(self, article_model, db):
        for i in range(5):
            article_model.objects.create(title=f"Article {i}", body=f"Body {i}", author="Author")

        signal_calls: list[int] = []

        def handler(sender, instance, count, **kwargs):
            signal_calls.append(count)

        documents_indexed.connect(handler)
        try:
            index_model_instances(article_model, bulk=True, batch_size=2)
        finally:
            documents_indexed.disconnect(handler)

        # Exactly one signal with the total count.
        assert len(signal_calls) == 1
        assert signal_calls[0] == 5

    def test_non_bulk_path_unchanged(self, article_model, db):
        """Default (non-bulk) path still works as before."""
        for i in range(5):
            article_model.objects.create(title=f"Article {i}", body=f"Body {i}", author="Author")

        total = index_model_instances(article_model, batch_size=2)
        assert total == 5


# ---------------------------------------------------------------------------
# reindex_zero_downtime(bulk=True)
# ---------------------------------------------------------------------------


class TestReindexZeroDowntimeBulk:
    @pytest.fixture()
    def article_model(self, backend, search_index):
        from search_testapp.models import Article

        return Article

    def test_bulk_reindex(self, article_model, db):
        for i in range(8):
            article_model.objects.create(title=f"Article {i}", body=f"Body {i}", author="Author")

        total = reindex_zero_downtime(
            article_model.search_index_name,
            article_model,
            bulk=True,
            batch_size=3,
        )
        assert total == 8

    def test_non_bulk_reindex_unchanged(self, article_model, db):
        for i in range(5):
            article_model.objects.create(title=f"Article {i}", body=f"Body {i}", author="Author")

        total = reindex_zero_downtime(
            article_model.search_index_name,
            article_model,
            batch_size=2,
        )
        assert total == 5

    def test_bulk_progress_callback(self, article_model, db):
        for i in range(6):
            article_model.objects.create(title=f"Article {i}", body=f"Body {i}", author="Author")

        calls: list[tuple[int, int]] = []
        reindex_zero_downtime(
            article_model.search_index_name,
            article_model,
            bulk=True,
            batch_size=2,
            progress_callback=lambda done, total: calls.append((done, total)),
        )

        assert len(calls) >= 1
        assert calls[-1][0] == 6
