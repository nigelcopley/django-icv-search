"""Tests for SearchableMixin."""

import pytest

from icv_search.mixins import SearchableMixin


class TestSearchableMixinClassAttributes:
    """Mixin declares the right class-level attributes."""

    def test_has_search_index_name(self):
        assert hasattr(SearchableMixin, "search_index_name")
        assert SearchableMixin.search_index_name == ""

    def test_has_search_fields(self):
        assert hasattr(SearchableMixin, "search_fields")
        assert isinstance(SearchableMixin.search_fields, list)

    def test_has_search_filterable_fields(self):
        assert hasattr(SearchableMixin, "search_filterable_fields")
        assert isinstance(SearchableMixin.search_filterable_fields, list)

    def test_has_search_sortable_fields(self):
        assert hasattr(SearchableMixin, "search_sortable_fields")
        assert isinstance(SearchableMixin.search_sortable_fields, list)


class TestSearchableMixinToSearchDocument:
    """to_search_document() serialises model fields correctly."""

    @pytest.mark.django_db
    def test_document_includes_id(self):
        from search_testapp.models import Article

        article = Article.objects.create(title="Hello", body="World", author="Bob")
        doc = article.to_search_document()
        assert doc["id"] == str(article.pk)

    @pytest.mark.django_db
    def test_document_includes_declared_fields(self):
        from search_testapp.models import Article

        article = Article.objects.create(title="Test Title", body="Test body", author="Alice")
        doc = article.to_search_document()
        assert doc["title"] == "Test Title"
        assert doc["body"] == "Test body"
        assert doc["author"] == "Alice"

    @pytest.mark.django_db
    def test_document_does_not_include_undeclared_fields(self):
        from search_testapp.models import Article

        article = Article.objects.create(title="Title", body="Body", author="Eve")
        doc = article.to_search_document()
        assert "is_published" not in doc  # not in search_fields

    @pytest.mark.django_db
    def test_document_converts_none_to_none(self):
        from search_testapp.models import Article

        article = Article.objects.create(title="Title")
        doc = article.to_search_document()
        assert "body" in doc  # body has default=""
        assert doc["author"] == ""  # author has default=""

    @pytest.mark.django_db
    def test_document_is_dict(self):
        from search_testapp.models import Article

        article = Article.objects.create(title="Dict test")
        doc = article.to_search_document()
        assert isinstance(doc, dict)


class TestSearchableMixinGetSearchQueryset:
    """get_search_queryset() returns all objects by default."""

    @pytest.mark.django_db
    def test_returns_all_objects(self):
        from search_testapp.models import Article

        Article.objects.create(title="One")
        Article.objects.create(title="Two")
        Article.objects.create(title="Three")

        qs = Article.get_search_queryset()
        assert qs.count() == 3

    @pytest.mark.django_db
    def test_returns_queryset(self):
        from django.db.models.query import QuerySet
        from search_testapp.models import Article

        qs = Article.get_search_queryset()
        assert isinstance(qs, QuerySet)


class TestIndexModelInstancesValidation:
    """index_model_instances raises when search_index_name is missing."""

    @pytest.mark.django_db
    def test_raises_if_no_search_index_name(self, settings):
        from icv_search.backends import reset_search_backend
        from icv_search.services.documents import index_model_instances

        settings.ICV_SEARCH_BACKEND = "icv_search.backends.dummy.DummyBackend"
        reset_search_backend()

        class NoIndexNameModel:
            search_index_name = ""

            @classmethod
            def get_search_queryset(cls):
                return []

        with pytest.raises(ValueError, match="does not define search_index_name"):
            index_model_instances(NoIndexNameModel)
