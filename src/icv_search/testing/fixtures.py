"""Pytest fixtures for icv-search testing."""

import pytest

from icv_search.backends import reset_search_backend
from icv_search.backends.dummy import DummyBackend
from icv_search.testing.factories import SearchIndexFactory


@pytest.fixture
def search_index(db):
    """Create a SearchIndex instance."""
    return SearchIndexFactory()


@pytest.fixture
def search_backend(settings):
    """Configure and return the DummyBackend for testing."""
    settings.ICV_SEARCH_BACKEND = "icv_search.backends.dummy.DummyBackend"
    reset_search_backend()
    DummyBackend.reset()
    yield DummyBackend
    DummyBackend.reset()
    reset_search_backend()


@pytest.fixture
def merchandising_enabled(settings):
    """Enable the merchandising layer for test scope."""
    settings.ICV_SEARCH_MERCHANDISING_ENABLED = True
    settings.ICV_SEARCH_MERCHANDISING_CACHE_TIMEOUT = 0
