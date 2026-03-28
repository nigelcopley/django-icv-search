"""Comprehensive tests for PostgresBackend.

These tests require a PostgreSQL database and django.contrib.postgres.
They are skipped when those dependencies are not available.
"""

from __future__ import annotations

import pytest

# Try to import postgres dependencies
try:
    import django.contrib.postgres  # noqa: F401
    from django.db import connection

    POSTGRES_AVAILABLE = connection.vendor == "postgres"
except ImportError:
    POSTGRES_AVAILABLE = False

from icv_search.exceptions import IndexNotFoundError

pytestmark = pytest.mark.skipif(
    not POSTGRES_AVAILABLE,
    reason="PostgreSQL backend tests require PostgreSQL database and django.contrib.postgres",
)


@pytest.fixture
def postgres_backend():
    """Instantiate a PostgresBackend for testing."""
    from icv_search.backends.postgres import PostgresBackend

    backend = PostgresBackend()
    yield backend
    # Cleanup: drop all test indexes
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM icv_search_document")
        cursor.execute("DELETE FROM icv_search_index_meta")


class TestPostgresBackendInit:
    """PostgresBackend initialisation."""

    def test_creates_tables_on_init(self, postgres_backend):
        """Backend should create document and metadata tables on init."""
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name IN ('icv_search_document', 'icv_search_index_meta')
                """
            )
            tables = [row[0] for row in cursor.fetchall()]
            assert "icv_search_document" in tables
            assert "icv_search_index_meta" in tables

    def test_creates_indexes_on_document_table(self, postgres_backend):
        """Backend should create GIN and B-tree indexes."""
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT indexname FROM pg_indexes
                WHERE tablename = 'icv_search_document'
                """
            )
            index_names = [row[0] for row in cursor.fetchall()]
            assert any("search_vector" in name for name in index_names)
            assert any("index_uid" in name for name in index_names)

    def test_ensure_tables_is_idempotent(self):
        """Calling _ensure_tables multiple times should not error."""
        from icv_search.backends.postgres import PostgresBackend

        # First call
        PostgresBackend()
        # Second call
        PostgresBackend()
        # Should not raise


class TestPostgresCreateIndex:
    """create_index method."""

    def test_creates_metadata_record(self, postgres_backend):
        """create_index should insert a row in the metadata table."""
        result = postgres_backend.create_index("test_index", primary_key="id")
        assert result["status"] == "succeeded"
        assert result["indexUid"] == "test_index"

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT primary_key FROM icv_search_index_meta WHERE index_uid = %s", ["test_index"])
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == "id"

    def test_uses_custom_primary_key(self, postgres_backend):
        """create_index should store the specified primary key."""
        postgres_backend.create_index("products", primary_key="product_id")

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT primary_key FROM icv_search_index_meta WHERE index_uid = %s", ["products"])
            row = cursor.fetchone()
            assert row[0] == "product_id"

    def test_is_idempotent(self, postgres_backend):
        """Creating the same index twice should update, not error."""
        postgres_backend.create_index("test_index", primary_key="id")
        # Second call with different primary key
        postgres_backend.create_index("test_index", primary_key="uuid")

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT primary_key FROM icv_search_index_meta WHERE index_uid = %s", ["test_index"])
            row = cursor.fetchone()
            assert row[0] == "uuid"

    def test_returns_task_result(self, postgres_backend):
        """create_index should return a dict with taskUid, indexUid, status."""
        result = postgres_backend.create_index("test_index")
        assert "taskUid" in result
        assert "indexUid" in result
        assert "status" in result
        assert result["status"] == "succeeded"


class TestPostgresDeleteIndex:
    """delete_index method."""

    def test_removes_metadata_record(self, postgres_backend):
        """delete_index should remove the metadata row."""
        postgres_backend.create_index("test_index")
        postgres_backend.delete_index("test_index")

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM icv_search_index_meta WHERE index_uid = %s", ["test_index"])
            count = cursor.fetchone()[0]
            assert count == 0

    def test_removes_all_documents(self, postgres_backend):
        """delete_index should delete all documents for that index."""
        postgres_backend.create_index("test_index")
        postgres_backend.add_documents("test_index", [{"id": "1"}, {"id": "2"}])
        postgres_backend.delete_index("test_index")

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM icv_search_document WHERE index_uid = %s", ["test_index"])
            count = cursor.fetchone()[0]
            assert count == 0

    def test_does_not_error_when_index_missing(self, postgres_backend):
        """Deleting a non-existent index should not raise."""
        postgres_backend.delete_index("nonexistent")
        # Should not raise


class TestPostgresUpdateSettings:
    """update_settings method."""

    def test_stores_settings_as_json(self, postgres_backend):
        """update_settings should store settings in the metadata table."""
        postgres_backend.create_index("test_index")
        settings = {"searchableAttributes": ["name", "description"]}
        postgres_backend.update_settings("test_index", settings)

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT settings FROM icv_search_index_meta WHERE index_uid = %s", ["test_index"])
            row = cursor.fetchone()
            stored = row[0]
            assert stored["searchableAttributes"] == ["name", "description"]

    def test_overwrites_existing_settings(self, postgres_backend):
        """Calling update_settings again should replace settings."""
        postgres_backend.create_index("test_index")
        postgres_backend.update_settings("test_index", {"a": 1})
        postgres_backend.update_settings("test_index", {"b": 2})

        stored = postgres_backend.get_settings("test_index")
        assert stored == {"b": 2}

    def test_raises_when_index_not_found(self, postgres_backend):
        """update_settings should raise IndexNotFoundError for missing index."""
        with pytest.raises(IndexNotFoundError, match="Index 'nonexistent' not found"):
            postgres_backend.update_settings("nonexistent", {})

    def test_returns_task_result(self, postgres_backend):
        """update_settings should return a dict with status."""
        postgres_backend.create_index("test_index")
        result = postgres_backend.update_settings("test_index", {})
        assert result["status"] == "succeeded"


class TestPostgresGetSettings:
    """get_settings method."""

    def test_retrieves_stored_settings(self, postgres_backend):
        """get_settings should return the settings dict."""
        postgres_backend.create_index("test_index")
        settings = {"filterableAttributes": ["category"]}
        postgres_backend.update_settings("test_index", settings)

        retrieved = postgres_backend.get_settings("test_index")
        assert retrieved == settings

    def test_returns_empty_dict_for_new_index(self, postgres_backend):
        """get_settings should return {} for newly created index."""
        postgres_backend.create_index("test_index")
        settings = postgres_backend.get_settings("test_index")
        assert settings == {}

    def test_raises_when_index_not_found(self, postgres_backend):
        """get_settings should raise IndexNotFoundError for missing index."""
        with pytest.raises(IndexNotFoundError, match="Index 'nonexistent' not found"):
            postgres_backend.get_settings("nonexistent")


class TestPostgresAddDocuments:
    """add_documents method."""

    def test_adds_documents_to_table(self, postgres_backend):
        """add_documents should insert rows in icv_search_document."""
        postgres_backend.create_index("test_index")
        docs = [{"id": "1", "name": "Widget"}, {"id": "2", "name": "Gadget"}]
        postgres_backend.add_documents("test_index", docs)

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT doc_id, body FROM icv_search_document WHERE index_uid = %s ORDER BY doc_id", ["test_index"]
            )
            rows = cursor.fetchall()
            assert len(rows) == 2
            assert rows[0][0] == "1"
            assert rows[0][1]["name"] == "Widget"

    def test_builds_search_vector(self, postgres_backend):
        """add_documents should create a tsvector for full-text search."""
        postgres_backend.create_index("test_index")
        docs = [{"id": "1", "name": "Django Framework"}]
        postgres_backend.add_documents("test_index", docs)

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT search_vector FROM icv_search_document WHERE doc_id = %s", ["1"])
            row = cursor.fetchone()
            assert row[0] is not None

    def test_updates_existing_document(self, postgres_backend):
        """add_documents should update existing documents with same ID."""
        postgres_backend.create_index("test_index")
        postgres_backend.add_documents("test_index", [{"id": "1", "name": "Old"}])
        postgres_backend.add_documents("test_index", [{"id": "1", "name": "New"}])

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT body FROM icv_search_document WHERE doc_id = %s", ["1"])
            row = cursor.fetchone()
            assert row[0]["name"] == "New"

    def test_uses_custom_primary_key(self, postgres_backend):
        """add_documents should use the specified primary_key field."""
        postgres_backend.create_index("test_index")
        docs = [{"product_id": "abc", "name": "Widget"}]
        postgres_backend.add_documents("test_index", docs, primary_key="product_id")

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT doc_id FROM icv_search_document WHERE index_uid = %s", ["test_index"])
            row = cursor.fetchone()
            assert row[0] == "abc"

    def test_respects_searchable_attributes(self, postgres_backend):
        """add_documents should only index configured searchable fields."""
        postgres_backend.create_index("test_index")
        postgres_backend.update_settings("test_index", {"searchableAttributes": ["name"]})
        docs = [{"id": "1", "name": "Widget", "description": "Secret"}]
        postgres_backend.add_documents("test_index", docs)

        # Search for a term only in the non-searchable field
        result = postgres_backend.search("test_index", "Secret")
        # Should not match because description is not searchable
        assert len(result["hits"]) == 0

        # Search for a term in the searchable field
        result = postgres_backend.search("test_index", "Widget")
        assert len(result["hits"]) == 1

    def test_handles_empty_document_list(self, postgres_backend):
        """add_documents should handle empty list gracefully."""
        postgres_backend.create_index("test_index")
        result = postgres_backend.add_documents("test_index", [])
        assert result["status"] == "succeeded"

    def test_returns_task_result(self, postgres_backend):
        """add_documents should return a dict with status."""
        postgres_backend.create_index("test_index")
        result = postgres_backend.add_documents("test_index", [{"id": "1"}])
        assert result["status"] == "succeeded"
        assert "taskUid" in result


class TestPostgresDeleteDocuments:
    """delete_documents method."""

    def test_removes_documents_by_id(self, postgres_backend):
        """delete_documents should remove specified documents."""
        postgres_backend.create_index("test_index")
        postgres_backend.add_documents("test_index", [{"id": "1"}, {"id": "2"}, {"id": "3"}])
        postgres_backend.delete_documents("test_index", ["1", "3"])

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT doc_id FROM icv_search_document WHERE index_uid = %s", ["test_index"])
            remaining = [row[0] for row in cursor.fetchall()]
            assert remaining == ["2"]

    def test_handles_empty_id_list(self, postgres_backend):
        """delete_documents should handle empty list gracefully."""
        postgres_backend.create_index("test_index")
        result = postgres_backend.delete_documents("test_index", [])
        assert result["status"] == "succeeded"

    def test_does_not_error_for_missing_ids(self, postgres_backend):
        """Deleting non-existent documents should not raise."""
        postgres_backend.create_index("test_index")
        postgres_backend.delete_documents("test_index", ["nonexistent"])
        # Should not raise

    def test_returns_task_result(self, postgres_backend):
        """delete_documents should return a dict with status."""
        postgres_backend.create_index("test_index")
        result = postgres_backend.delete_documents("test_index", ["1"])
        assert result["status"] == "succeeded"


class TestPostgresClearDocuments:
    """clear_documents method."""

    def test_removes_all_documents_from_index(self, postgres_backend):
        """clear_documents should delete all documents for the index."""
        postgres_backend.create_index("test_index")
        postgres_backend.add_documents("test_index", [{"id": "1"}, {"id": "2"}])
        postgres_backend.clear_documents("test_index")

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM icv_search_document WHERE index_uid = %s", ["test_index"])
            count = cursor.fetchone()[0]
            assert count == 0

    def test_does_not_remove_metadata(self, postgres_backend):
        """clear_documents should preserve the index metadata."""
        postgres_backend.create_index("test_index")
        postgres_backend.update_settings("test_index", {"searchableAttributes": ["name"]})
        postgres_backend.clear_documents("test_index")

        settings = postgres_backend.get_settings("test_index")
        assert settings == {"searchableAttributes": ["name"]}

    def test_returns_task_result(self, postgres_backend):
        """clear_documents should return a dict with status."""
        postgres_backend.create_index("test_index")
        result = postgres_backend.clear_documents("test_index")
        assert result["status"] == "succeeded"


class TestPostgresSearch:
    """search method."""

    def test_returns_all_documents_with_empty_query(self, postgres_backend):
        """Empty query should return all documents."""
        postgres_backend.create_index("test_index")
        postgres_backend.add_documents("test_index", [{"id": "1"}, {"id": "2"}])
        result = postgres_backend.search("test_index", "")
        assert len(result["hits"]) == 2
        assert result["estimatedTotalHits"] == 2

    def test_full_text_search(self, postgres_backend):
        """search should perform full-text matching."""
        postgres_backend.create_index("test_index")
        docs = [
            {"id": "1", "title": "Django Tutorial"},
            {"id": "2", "title": "Python Guide"},
            {"id": "3", "title": "Django REST Framework"},
        ]
        postgres_backend.add_documents("test_index", docs)
        result = postgres_backend.search("test_index", "Django")
        assert len(result["hits"]) == 2

    def test_filters_by_exact_match(self, postgres_backend):
        """search should apply dict filters."""
        postgres_backend.create_index("test_index")
        docs = [
            {"id": "1", "category": "A", "active": True},
            {"id": "2", "category": "B", "active": True},
            {"id": "3", "category": "A", "active": False},
        ]
        postgres_backend.add_documents("test_index", docs)
        result = postgres_backend.search("test_index", "", filter={"category": "A", "active": True})
        assert len(result["hits"]) == 1
        assert result["hits"][0]["id"] == "1"

    def test_filters_by_list_values(self, postgres_backend):
        """search should support IN filters with list values."""
        postgres_backend.create_index("test_index")
        docs = [
            {"id": "1", "category": "A"},
            {"id": "2", "category": "B"},
            {"id": "3", "category": "C"},
        ]
        postgres_backend.add_documents("test_index", docs)
        result = postgres_backend.search("test_index", "", filter={"category": ["A", "C"]})
        assert len(result["hits"]) == 2

    def test_sorts_ascending(self, postgres_backend):
        """search should sort by specified fields ascending."""
        postgres_backend.create_index("test_index")
        docs = [
            {"id": "1", "price": "30"},
            {"id": "2", "price": "10"},
            {"id": "3", "price": "20"},
        ]
        postgres_backend.add_documents("test_index", docs)
        result = postgres_backend.search("test_index", "", sort=["price"])
        assert result["hits"][0]["id"] == "2"
        assert result["hits"][1]["id"] == "3"
        assert result["hits"][2]["id"] == "1"

    def test_sorts_descending(self, postgres_backend):
        """search should sort descending when field prefixed with -."""
        postgres_backend.create_index("test_index")
        docs = [
            {"id": "1", "price": "30"},
            {"id": "2", "price": "10"},
            {"id": "3", "price": "20"},
        ]
        postgres_backend.add_documents("test_index", docs)
        result = postgres_backend.search("test_index", "", sort=["-price"])
        assert result["hits"][0]["id"] == "1"

    def test_applies_limit(self, postgres_backend):
        """search should respect limit parameter."""
        postgres_backend.create_index("test_index")
        postgres_backend.add_documents("test_index", [{"id": str(i)} for i in range(10)])
        result = postgres_backend.search("test_index", "", limit=3)
        assert len(result["hits"]) == 3

    def test_applies_offset(self, postgres_backend):
        """search should respect offset parameter."""
        postgres_backend.create_index("test_index")
        postgres_backend.add_documents("test_index", [{"id": str(i), "val": i} for i in range(10)])
        result = postgres_backend.search("test_index", "", sort=["val"], offset=5, limit=2)
        assert len(result["hits"]) == 2
        assert result["hits"][0]["val"] == 5

    def test_returns_processing_time(self, postgres_backend):
        """search should return processingTimeMs."""
        postgres_backend.create_index("test_index")
        result = postgres_backend.search("test_index", "")
        assert "processingTimeMs" in result
        assert result["processingTimeMs"] >= 0

    def test_returns_query_in_response(self, postgres_backend):
        """search should echo the query in the response."""
        postgres_backend.create_index("test_index")
        result = postgres_backend.search("test_index", "test query")
        assert result["query"] == "test query"


class TestPostgresGetStats:
    """get_stats method."""

    def test_returns_document_count(self, postgres_backend):
        """get_stats should return numberOfDocuments."""
        postgres_backend.create_index("test_index")
        postgres_backend.add_documents("test_index", [{"id": "1"}, {"id": "2"}])
        stats = postgres_backend.get_stats("test_index")
        assert stats["numberOfDocuments"] == 2

    def test_returns_is_indexing_false(self, postgres_backend):
        """get_stats should return isIndexing=False (synchronous backend)."""
        postgres_backend.create_index("test_index")
        stats = postgres_backend.get_stats("test_index")
        assert stats["isIndexing"] is False


class TestPostgresHealth:
    """health method."""

    def test_returns_true_when_connected(self, postgres_backend):
        """health should return True when PostgreSQL is reachable."""
        assert postgres_backend.health() is True

    def test_returns_false_on_connection_error(self):
        """health should return False when database is unreachable."""
        from unittest.mock import patch

        from icv_search.backends.postgres import PostgresBackend

        backend = PostgresBackend()
        with patch("django.db.connection.cursor", side_effect=Exception("connection failed")):
            assert backend.health() is False


class TestPostgresGetTask:
    """get_task method."""

    def test_always_returns_succeeded(self, postgres_backend):
        """get_task should always return succeeded (synchronous backend)."""
        result = postgres_backend.get_task("any-task-uid")
        assert result["status"] == "succeeded"
        assert result["uid"] == "any-task-uid"
