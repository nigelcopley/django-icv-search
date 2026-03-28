"""Tests for icv-search models."""

import pytest
from django.utils import timezone

from icv_search.models import IndexSyncLog, SearchIndex
from icv_search.testing.factories import IndexSyncLogFactory, SearchIndexFactory


class TestSearchIndex:
    """SearchIndex model: field definitions and computed properties."""

    def test_has_name_field(self):
        field = SearchIndex._meta.get_field("name")
        assert field.max_length == 100
        assert field.db_index is True

    def test_has_tenant_id_field(self):
        field = SearchIndex._meta.get_field("tenant_id")
        assert field.blank is True
        assert field.default == ""
        assert field.db_index is True

    def test_has_engine_uid_field(self):
        field = SearchIndex._meta.get_field("engine_uid")
        assert field.unique is True
        assert field.editable is False

    def test_has_is_synced_field(self):
        field = SearchIndex._meta.get_field("is_synced")
        assert field.default is False

    def test_has_is_active_field(self):
        field = SearchIndex._meta.get_field("is_active")
        assert field.default is True
        assert field.db_index is True

    def test_has_settings_field(self):
        field = SearchIndex._meta.get_field("settings")
        assert callable(field.default)

    def test_ordering(self):
        assert SearchIndex._meta.ordering == ["name"]

    def test_unique_together(self):
        constraints = SearchIndex._meta.unique_together
        assert ("tenant_id", "name") in constraints


class TestSearchIndexEngineUid:
    """engine_uid computation rules."""

    @pytest.mark.django_db
    def test_engine_uid_without_tenant_or_prefix(self):
        index = SearchIndexFactory(name="products", tenant_id="")
        assert index.engine_uid == "products"

    @pytest.mark.django_db
    def test_engine_uid_with_tenant(self):
        index = SearchIndexFactory(name="products", tenant_id="acme")
        assert index.engine_uid == "acme_products"

    @pytest.mark.django_db
    def test_engine_uid_with_prefix(self, settings):
        settings.ICV_SEARCH_INDEX_PREFIX = "staging_"
        index = SearchIndexFactory(name="products", tenant_id="")
        # Re-save to pick up new prefix
        index.save()
        index.refresh_from_db()
        assert index.engine_uid == "staging_products"

    @pytest.mark.django_db
    def test_engine_uid_with_prefix_and_tenant(self, settings):
        settings.ICV_SEARCH_INDEX_PREFIX = "prod_"
        index = SearchIndexFactory(name="orders", tenant_id="shop1")
        index.save()
        index.refresh_from_db()
        assert index.engine_uid == "prod_shop1_orders"

    @pytest.mark.django_db
    def test_engine_uid_computed_on_save(self):
        index = SearchIndex(name="invoices", tenant_id="")
        index.save()
        assert index.engine_uid == "invoices"

    @pytest.mark.django_db
    def test_engine_uid_updates_on_resave(self):
        index = SearchIndexFactory(name="docs", tenant_id="")
        original_uid = index.engine_uid
        index.tenant_id = "tenant1"
        index.save()
        index.refresh_from_db()
        assert index.engine_uid != original_uid
        assert index.engine_uid == "tenant1_docs"


class TestSearchIndexTenantPrefixFunc:
    """engine_uid computation with ICV_SEARCH_TENANT_PREFIX_FUNC."""

    @pytest.mark.django_db
    def test_tenant_prefix_func_used_when_no_explicit_tenant(self, settings, monkeypatch):
        """When tenant_id is blank and TENANT_PREFIX_FUNC is set, its return value
        is used as the tenant segment of the engine_uid."""
        settings.ICV_SEARCH_TENANT_PREFIX_FUNC = "tests.helpers.get_test_tenant"
        monkeypatch.setattr(
            "django.utils.module_loading.import_string",
            lambda path: lambda req: "org42",
        )
        index = SearchIndex(name="products", tenant_id="")
        index.save()
        assert index.engine_uid == "org42_products"

    @pytest.mark.django_db
    def test_explicit_tenant_id_takes_precedence_over_func(self, settings, monkeypatch):
        """An explicit tenant_id on the instance must win over any callable result."""
        settings.ICV_SEARCH_TENANT_PREFIX_FUNC = "tests.helpers.get_test_tenant"
        monkeypatch.setattr(
            "django.utils.module_loading.import_string",
            lambda path: lambda req: "org42",
        )
        index = SearchIndex(name="products", tenant_id="explicit")
        index.save()
        assert index.engine_uid == "explicit_products"

    @pytest.mark.django_db
    def test_func_returning_empty_string_gives_no_tenant_segment(self, settings, monkeypatch):
        """If the callable returns an empty string, the uid has no tenant segment."""
        settings.ICV_SEARCH_TENANT_PREFIX_FUNC = "tests.helpers.get_test_tenant"
        monkeypatch.setattr(
            "django.utils.module_loading.import_string",
            lambda path: lambda req: "",
        )
        index = SearchIndex(name="products", tenant_id="")
        index.save()
        assert index.engine_uid == "products"

    @pytest.mark.django_db
    def test_empty_tenant_prefix_func_setting_is_ignored(self, settings):
        """An empty ICV_SEARCH_TENANT_PREFIX_FUNC leaves single-tenant behaviour intact."""
        settings.ICV_SEARCH_TENANT_PREFIX_FUNC = ""
        index = SearchIndex(name="products", tenant_id="")
        index.save()
        assert index.engine_uid == "products"


class TestSearchIndexStr:
    """SearchIndex.__str__ formatting."""

    @pytest.mark.django_db
    def test_str_without_tenant(self):
        index = SearchIndexFactory(name="products", tenant_id="")
        assert str(index) == "products"

    @pytest.mark.django_db
    def test_str_with_tenant(self):
        index = SearchIndexFactory(name="products", tenant_id="acme")
        assert str(index) == "products (tenant: acme)"


class TestSearchIndexMarkSynced:
    """SearchIndex.mark_synced() behaviour."""

    @pytest.mark.django_db
    def test_mark_synced_sets_is_synced_true(self):
        index = SearchIndexFactory()
        assert index.is_synced is False
        index.mark_synced()
        index.refresh_from_db()
        assert index.is_synced is True

    @pytest.mark.django_db
    def test_mark_synced_sets_last_synced_at(self):
        index = SearchIndexFactory()
        assert index.last_synced_at is None
        before = timezone.now()
        index.mark_synced()
        index.refresh_from_db()
        assert index.last_synced_at is not None
        assert index.last_synced_at >= before

    @pytest.mark.django_db
    def test_mark_synced_uses_update_not_save(self):
        """mark_synced() must not trigger the post_save signal again."""
        index = SearchIndexFactory()
        # Patch post_save to detect if it fires
        signal_calls = []
        from django.db.models.signals import post_save

        def handler(sender, instance, **kwargs):
            signal_calls.append(instance)

        post_save.connect(handler, sender=SearchIndex)
        try:
            signal_calls.clear()
            index.mark_synced()
            # post_save should NOT have fired (update() bypasses signals)
            assert len(signal_calls) == 0
        finally:
            post_save.disconnect(handler, sender=SearchIndex)


class TestIndexSyncLog:
    """IndexSyncLog model: fields, creation, and mark_complete."""

    def test_has_action_field(self):
        field = IndexSyncLog._meta.get_field("action")
        assert field.max_length == 50

    def test_has_status_field_with_default(self):
        field = IndexSyncLog._meta.get_field("status")
        assert field.default == "pending"

    def test_has_detail_field(self):
        field = IndexSyncLog._meta.get_field("detail")
        assert field.blank is True

    def test_has_task_uid_field(self):
        field = IndexSyncLog._meta.get_field("task_uid")
        assert field.blank is True

    def test_ordering(self):
        assert IndexSyncLog._meta.ordering == ["-created_at"]

    @pytest.mark.django_db
    def test_str(self):
        log = IndexSyncLogFactory(action="created", status="success")
        assert "created" in str(log)
        assert "success" in str(log)

    @pytest.mark.django_db
    def test_mark_complete_sets_status(self):
        log = IndexSyncLogFactory(status="pending")
        log.mark_complete(status="success")
        log.refresh_from_db()
        assert log.status == "success"

    @pytest.mark.django_db
    def test_mark_complete_sets_detail(self):
        log = IndexSyncLogFactory(status="pending")
        log.mark_complete(status="failed", detail="Connection refused.")
        log.refresh_from_db()
        assert log.detail == "Connection refused."

    @pytest.mark.django_db
    def test_mark_complete_sets_completed_at(self):
        log = IndexSyncLogFactory(status="pending")
        assert log.completed_at is None
        before = timezone.now()
        log.mark_complete()
        log.refresh_from_db()
        assert log.completed_at is not None
        assert log.completed_at >= before

    @pytest.mark.django_db
    def test_mark_complete_defaults_to_success(self):
        log = IndexSyncLogFactory(status="pending")
        log.mark_complete()
        log.refresh_from_db()
        assert log.status == "success"

    @pytest.mark.django_db
    def test_unique_together_tenant_name(self):
        from django.db import IntegrityError

        SearchIndexFactory(name="products", tenant_id="")
        with pytest.raises(IntegrityError):
            SearchIndexFactory(name="products", tenant_id="")
