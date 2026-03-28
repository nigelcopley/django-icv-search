"""Tests for the delete_document() convenience service function."""

from __future__ import annotations

import pytest

from icv_search.backends import reset_search_backend
from icv_search.backends.dummy import DummyBackend
from icv_search.services import create_index, delete_document, index_documents, search
from icv_search.types import TaskResult


@pytest.fixture(autouse=True)
def use_dummy_backend(settings):
    settings.ICV_SEARCH_BACKEND = "icv_search.backends.dummy.DummyBackend"
    settings.ICV_SEARCH_AUTO_SYNC = False
    reset_search_backend()
    DummyBackend.reset()
    yield
    DummyBackend.reset()
    reset_search_backend()


@pytest.fixture()
def products_index():
    index = create_index("products")
    index_documents(
        index,
        [
            {"id": "1", "title": "Running Shoes"},
            {"id": "2", "title": "Tennis Racket"},
            {"id": "3", "title": "Golf Club"},
        ],
    )
    return index


class TestDeleteDocument:
    """delete_document() service function (BR-011)."""

    @pytest.mark.django_db
    def test_returns_task_result(self, products_index):
        result = delete_document("products", "1")
        assert isinstance(result, TaskResult)

    @pytest.mark.django_db
    def test_removes_single_document(self, products_index):
        delete_document("products", "1")
        result = search("products", "", limit=10)
        ids = [h["id"] for h in result.hits]
        assert "1" not in ids
        assert "2" in ids
        assert "3" in ids

    @pytest.mark.django_db
    def test_other_documents_unaffected(self, products_index):
        delete_document("products", "2")
        result = search("products", "", limit=10)
        assert len(result.hits) == 2
        ids = [h["id"] for h in result.hits]
        assert "1" in ids
        assert "3" in ids

    @pytest.mark.django_db
    def test_accepts_index_instance(self, products_index):
        delete_document(products_index, "1")
        result = search("products", "", limit=10)
        ids = [h["id"] for h in result.hits]
        assert "1" not in ids

    @pytest.mark.django_db
    def test_with_tenant_id(self):
        create_index("products", tenant_id="t1")
        index_documents("products", [{"id": "1", "title": "A"}], tenant_id="t1")

        delete_document("products", "1", tenant_id="t1")
        result = search("products", "", tenant_id="t1", limit=10)
        assert len(result.hits) == 0

    @pytest.mark.django_db
    def test_nonexistent_document_does_not_raise(self, products_index):
        """Deleting a document that doesn't exist should not raise."""
        result = delete_document("products", "nonexistent")
        assert isinstance(result, TaskResult)


class TestDeleteDocumentExport:
    """delete_document is correctly exported."""

    def test_importable_from_services(self):
        from icv_search.services import delete_document as dd

        assert callable(dd)

    def test_in_services_all(self):
        from icv_search.services import __all__

        assert "delete_document" in __all__


class TestSearchQueryLogFactoryExport:
    """SearchQueryLogFactory is correctly exported from testing."""

    def test_importable_from_testing(self):
        from icv_search.testing import SearchQueryLogFactory

        assert SearchQueryLogFactory is not None

    def test_in_testing_all(self):
        from icv_search.testing import __all__

        assert "SearchQueryLogFactory" in __all__
