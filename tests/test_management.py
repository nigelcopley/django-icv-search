"""Tests for icv-search management commands."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from icv_search.backends import reset_search_backend
from icv_search.backends.dummy import DummyBackend, _indexes
from icv_search.models import SearchIndex
from icv_search.services import create_index, index_documents
from icv_search.testing.factories import SearchIndexFactory


@pytest.fixture(autouse=True)
def use_dummy_backend(settings):
    """Use DummyBackend for all management command tests."""
    settings.ICV_SEARCH_BACKEND = "icv_search.backends.dummy.DummyBackend"
    settings.ICV_SEARCH_AUTO_SYNC = False
    reset_search_backend()
    DummyBackend.reset()
    yield
    DummyBackend.reset()
    reset_search_backend()


class TestIcvSearchHealthCommand:
    """icv_search_health management command."""

    @pytest.mark.django_db
    def test_reports_healthy_engine(self):
        out = StringIO()
        call_command("icv_search_health", stdout=out)
        assert "healthy" in out.getvalue().lower()

    @pytest.mark.django_db
    def test_verbose_shows_index_count(self):
        create_index("products")
        create_index("articles")
        out = StringIO()
        call_command("icv_search_health", "--verbose", stdout=out)
        output = out.getvalue()
        assert "Active indexes: 2" in output

    @pytest.mark.django_db
    def test_verbose_shows_each_index(self):
        create_index("products")
        out = StringIO()
        call_command("icv_search_health", "--verbose", stdout=out)
        assert "products" in out.getvalue()

    @pytest.mark.django_db
    def test_unhealthy_engine_reports_error(self):
        from unittest.mock import patch

        backend = DummyBackend.__new__(DummyBackend)
        backend.health = lambda: False

        with patch(
            "icv_search.management.commands.icv_search_health.get_search_backend",
            return_value=backend,
        ):
            out = StringIO()
            call_command("icv_search_health", stdout=out)
            assert "unreachable" in out.getvalue().lower()


class TestIcvSearchCreateIndexCommand:
    """icv_search_create_index management command."""

    @pytest.mark.django_db
    def test_creates_index_in_database(self):
        call_command("icv_search_create_index", "--name=products")
        assert SearchIndex.objects.filter(name="products").exists()

    @pytest.mark.django_db
    def test_creates_index_in_engine(self):
        call_command("icv_search_create_index", "--name=orders")
        index = SearchIndex.objects.get(name="orders")
        assert index.engine_uid in _indexes

    @pytest.mark.django_db
    def test_creates_index_with_custom_primary_key(self):
        call_command("icv_search_create_index", "--name=invoices", "--primary-key=invoice_id")
        index = SearchIndex.objects.get(name="invoices")
        assert index.primary_key_field == "invoice_id"

    @pytest.mark.django_db
    def test_creates_index_with_tenant(self):
        call_command("icv_search_create_index", "--name=products", "--tenant=acme")
        index = SearchIndex.objects.get(name="products", tenant_id="acme")
        assert index.engine_uid == "acme_products"

    @pytest.mark.django_db
    def test_outputs_success_message(self):
        out = StringIO()
        call_command("icv_search_create_index", "--name=widgets", stdout=out)
        output = out.getvalue()
        assert "widgets" in output
        assert "Created" in output


class TestIcvSearchClearCommand:
    """icv_search_clear management command."""

    @pytest.mark.django_db
    def test_clears_documents_from_engine(self):
        index = create_index("products")
        index_documents(index, [{"id": "1"}, {"id": "2"}])

        call_command("icv_search_clear", "--index=products")

        from icv_search.backends.dummy import _documents

        assert _documents.get(index.engine_uid, {}) == {}

    @pytest.mark.django_db
    def test_resets_document_count_in_database(self):
        index = create_index("products")
        SearchIndex.objects.filter(pk=index.pk).update(document_count=42)

        call_command("icv_search_clear", "--index=products")

        index.refresh_from_db()
        assert index.document_count == 0

    @pytest.mark.django_db
    def test_raises_command_error_for_missing_index(self):
        with pytest.raises(CommandError, match="not found"):
            call_command("icv_search_clear", "--index=nonexistent")

    @pytest.mark.django_db
    def test_outputs_success_message(self):
        create_index("articles")
        out = StringIO()
        call_command("icv_search_clear", "--index=articles", stdout=out)
        assert "Cleared" in out.getvalue()


class TestIcvSearchSyncCommand:
    """icv_search_sync management command."""

    @pytest.mark.django_db
    def test_syncs_unsynced_indexes(self):
        index = SearchIndexFactory(is_synced=False)
        # Ensure the engine index exists
        DummyBackend().create_index(index.engine_uid)

        out = StringIO()
        call_command("icv_search_sync", stdout=out)
        assert "Synced" in out.getvalue()

    @pytest.mark.django_db
    def test_skips_already_synced_without_force(self):
        SearchIndexFactory(is_synced=True)
        out = StringIO()
        call_command("icv_search_sync", stdout=out)
        assert "No indexes to sync" in out.getvalue()

    @pytest.mark.django_db
    def test_force_resyncs_already_synced(self):
        index = SearchIndexFactory(is_synced=True)
        DummyBackend().create_index(index.engine_uid)
        out = StringIO()
        call_command("icv_search_sync", "--force", stdout=out)
        assert "No indexes to sync" not in out.getvalue()

    @pytest.mark.django_db
    def test_filters_by_index_name(self):
        idx1 = SearchIndexFactory(name="products", is_synced=False)
        idx2 = SearchIndexFactory(name="articles", is_synced=False)
        DummyBackend().create_index(idx1.engine_uid)
        DummyBackend().create_index(idx2.engine_uid)

        out = StringIO()
        call_command("icv_search_sync", "--index=products", stdout=out)
        output = out.getvalue()
        assert "products" in output


class TestIcvSearchReindexCommand:
    """icv_search_reindex management command."""

    @pytest.mark.django_db
    def test_raises_command_error_for_missing_index(self):
        with pytest.raises(CommandError, match="not found"):
            call_command(
                "icv_search_reindex",
                "--index=nonexistent",
                "--model=search_testapp.models.Article",
            )

    @pytest.mark.django_db
    def test_raises_command_error_for_bad_model_path(self):
        create_index("articles")
        with pytest.raises(CommandError, match="Cannot import model"):
            call_command(
                "icv_search_reindex",
                "--index=articles",
                "--model=nonexistent.Model",
            )


class TestIcvSearchSetupCommand:
    """icv_search_setup management command."""

    @pytest.mark.django_db
    def test_creates_missing_indexes(self, settings):
        settings.ICV_SEARCH_AUTO_INDEX = {
            "articles": {"model": "search_testapp.Article"},
        }
        out = StringIO()
        call_command("icv_search_setup", stdout=out)
        assert SearchIndex.objects.filter(name="articles").exists()
        assert "Created" in out.getvalue()

    @pytest.mark.django_db
    def test_skips_existing_indexes(self, settings):
        settings.ICV_SEARCH_AUTO_INDEX = {
            "articles": {"model": "search_testapp.Article"},
        }
        create_index("articles")
        out = StringIO()
        call_command("icv_search_setup", stdout=out)
        assert SearchIndex.objects.filter(name="articles").count() == 1
        assert "record exists" in out.getvalue()

    @pytest.mark.django_db
    def test_syncs_unsynced_existing_index(self, settings):
        settings.ICV_SEARCH_AUTO_INDEX = {
            "articles": {"model": "search_testapp.Article"},
        }
        index = SearchIndexFactory(name="articles", is_synced=False)
        DummyBackend().create_index(index.engine_uid)

        out = StringIO()
        call_command("icv_search_setup", stdout=out)
        assert "Synced settings" in out.getvalue()

    @pytest.mark.django_db
    def test_dry_run_does_not_create(self, settings):
        settings.ICV_SEARCH_AUTO_INDEX = {
            "articles": {"model": "search_testapp.Article"},
        }
        out = StringIO()
        call_command("icv_search_setup", "--dry-run", stdout=out)
        assert not SearchIndex.objects.filter(name="articles").exists()
        assert "Would create" in out.getvalue()
        assert "Dry run" in out.getvalue()

    @pytest.mark.django_db
    def test_reports_healthy_engine(self, settings):
        settings.ICV_SEARCH_AUTO_INDEX = {}
        out = StringIO()
        call_command("icv_search_setup", stdout=out)
        assert "healthy" in out.getvalue().lower()

    @pytest.mark.django_db
    def test_warns_when_no_auto_index_config(self, settings):
        settings.ICV_SEARCH_AUTO_INDEX = {}
        out = StringIO()
        call_command("icv_search_setup", stdout=out)
        assert "No ICV_SEARCH_AUTO_INDEX" in out.getvalue()

    @pytest.mark.django_db
    def test_handles_unresolvable_model(self, settings):
        settings.ICV_SEARCH_AUTO_INDEX = {
            "broken": {"model": "nonexistent.FakeModel"},
        }
        out = StringIO()
        call_command("icv_search_setup", stdout=out)
        assert "Could not resolve" in out.getvalue()

    @pytest.mark.django_db
    def test_reports_summary(self, settings):
        settings.ICV_SEARCH_AUTO_INDEX = {
            "articles": {"model": "search_testapp.Article"},
        }
        out = StringIO()
        call_command("icv_search_setup", stdout=out)
        assert "Setup complete" in out.getvalue()
