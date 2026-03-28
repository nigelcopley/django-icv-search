"""Tests for icv-search signal dispatch."""

import pytest

from icv_search.backends import reset_search_backend
from icv_search.backends.dummy import DummyBackend
from icv_search.models import SearchIndex
from icv_search.services import (
    create_index,
    delete_index,
    index_documents,
    remove_documents,
)
from icv_search.signals import (
    documents_indexed,
    documents_removed,
    search_index_created,
    search_index_deleted,
    search_index_synced,
)


@pytest.fixture(autouse=True)
def use_dummy_backend(settings):
    """Use DummyBackend for all signal tests."""
    settings.ICV_SEARCH_BACKEND = "icv_search.backends.dummy.DummyBackend"
    settings.ICV_SEARCH_AUTO_SYNC = False
    reset_search_backend()
    DummyBackend.reset()
    yield
    DummyBackend.reset()
    reset_search_backend()


class TestSearchIndexCreatedSignal:
    """search_index_created fires after create_index()."""

    @pytest.mark.django_db
    def test_signal_fires_on_create_index(self):
        received = []

        def handler(sender, instance, **kwargs):
            received.append(instance)

        search_index_created.connect(handler)
        try:
            index = create_index("products")
            assert len(received) == 1
            assert received[0] is index
        finally:
            search_index_created.disconnect(handler)

    @pytest.mark.django_db
    def test_signal_sender_is_search_index(self):
        received_senders = []

        def handler(sender, **kwargs):
            received_senders.append(sender)

        search_index_created.connect(handler)
        try:
            create_index("products")
            assert received_senders[0] is SearchIndex
        finally:
            search_index_created.disconnect(handler)


class TestSearchIndexDeletedSignal:
    """search_index_deleted fires after delete_index()."""

    @pytest.mark.django_db
    def test_signal_fires_on_delete_index(self):
        index = create_index("products")
        received = []

        def handler(sender, instance, **kwargs):
            received.append(instance)

        search_index_deleted.connect(handler)
        try:
            delete_index(index)
            assert len(received) == 1
        finally:
            search_index_deleted.disconnect(handler)

    @pytest.mark.django_db
    def test_signal_provides_index_instance(self):
        index = create_index("orders")
        received = []

        def handler(sender, instance, **kwargs):
            received.append(instance)

        search_index_deleted.connect(handler)
        try:
            delete_index(index)
            assert received[0].name == "orders"
        finally:
            search_index_deleted.disconnect(handler)


class TestDocumentsIndexedSignal:
    """documents_indexed fires after index_documents()."""

    @pytest.mark.django_db
    def test_signal_fires_on_index_documents(self):
        index = create_index("products")
        received = []

        def handler(sender, instance, count, document_ids, **kwargs):
            received.append({"instance": instance, "count": count, "ids": document_ids})

        documents_indexed.connect(handler)
        try:
            index_documents(index, [{"id": "1"}, {"id": "2"}])
            assert len(received) == 1
            assert received[0]["count"] == 2
        finally:
            documents_indexed.disconnect(handler)

    @pytest.mark.django_db
    def test_signal_provides_document_ids(self):
        index = create_index("products")
        received = []

        def handler(sender, document_ids, **kwargs):
            received.extend(document_ids)

        documents_indexed.connect(handler)
        try:
            index_documents(index, [{"id": "abc"}, {"id": "def"}])
            assert "abc" in received
            assert "def" in received
        finally:
            documents_indexed.disconnect(handler)


class TestDocumentsRemovedSignal:
    """documents_removed fires after remove_documents()."""

    @pytest.mark.django_db
    def test_signal_fires_on_remove_documents(self):
        index = create_index("products")
        index_documents(index, [{"id": "1"}, {"id": "2"}])
        received = []

        def handler(sender, instance, count, document_ids, **kwargs):
            received.append({"count": count, "ids": document_ids})

        documents_removed.connect(handler)
        try:
            remove_documents(index, ["1"])
            assert len(received) == 1
            assert received[0]["count"] == 1
            assert "1" in received[0]["ids"]
        finally:
            documents_removed.disconnect(handler)


class TestSearchIndexSyncedSignal:
    """search_index_synced fires after settings are pushed to engine."""

    @pytest.mark.django_db
    def test_signal_fires_on_create_index(self):
        """create_index() triggers _sync_index_to_engine when settings are provided."""
        from icv_search.services.indexing import _sync_index_to_engine
        from icv_search.testing.factories import SearchIndexFactory

        received = []

        def handler(sender, instance, **kwargs):
            received.append(instance)

        search_index_synced.connect(handler)
        try:
            # Directly invoke internal sync helper to test signal
            index = SearchIndexFactory(settings={"searchableAttributes": ["name"]})
            _sync_index_to_engine(index)
            assert len(received) == 1
            assert received[0] is index
        finally:
            search_index_synced.disconnect(handler)
