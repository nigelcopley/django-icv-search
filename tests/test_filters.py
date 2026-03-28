"""Tests for filter/sort translation utilities and DummyBackend filter support."""

import pytest

from icv_search.backends.filters import (
    apply_filters_to_documents,
    apply_sort_to_documents,
    translate_filter_to_meilisearch,
    translate_sort_to_meilisearch,
)


class TestTranslateFilterToMeilisearch:
    def test_string_passthrough(self):
        assert translate_filter_to_meilisearch("city = 'Madrid'") == "city = 'Madrid'"

    def test_empty_dict(self):
        assert translate_filter_to_meilisearch({}) == ""

    def test_string_value(self):
        result = translate_filter_to_meilisearch({"city": "Madrid"})
        assert result == "city = 'Madrid'"

    def test_boolean_value(self):
        result = translate_filter_to_meilisearch({"is_active": True})
        assert result == "is_active = true"

    def test_boolean_false_value(self):
        result = translate_filter_to_meilisearch({"is_active": False})
        assert result == "is_active = false"

    def test_numeric_value(self):
        result = translate_filter_to_meilisearch({"price": 150})
        assert result == "price = 150"

    def test_float_value(self):
        result = translate_filter_to_meilisearch({"score": 9.5})
        assert result == "score = 9.5"

    def test_list_value(self):
        result = translate_filter_to_meilisearch({"category": ["a", "b"]})
        assert result == "category IN ['a', 'b']"

    def test_list_with_numeric_values(self):
        result = translate_filter_to_meilisearch({"price": [10, 20, 30]})
        assert result == "price IN [10, 20, 30]"

    def test_multiple_conditions(self):
        result = translate_filter_to_meilisearch({"city": "Madrid", "is_active": True})
        assert "city = 'Madrid'" in result
        assert "is_active = true" in result
        assert " AND " in result

    def test_none_value(self):
        result = translate_filter_to_meilisearch({"field": None})
        assert result == "field IS NULL"


class TestTranslateSortToMeilisearch:
    def test_descending(self):
        assert translate_sort_to_meilisearch(["-price"]) == ["price:desc"]

    def test_ascending(self):
        assert translate_sort_to_meilisearch(["name"]) == ["name:asc"]

    def test_passthrough_meilisearch_format(self):
        assert translate_sort_to_meilisearch(["price:desc"]) == ["price:desc"]

    def test_multiple_fields(self):
        result = translate_sort_to_meilisearch(["-price", "name"])
        assert result == ["price:desc", "name:asc"]

    def test_empty_list(self):
        assert translate_sort_to_meilisearch([]) == []

    def test_string_passthrough(self):
        assert translate_sort_to_meilisearch("price:desc") == ["price:desc"]

    def test_empty_string_returns_empty_list(self):
        assert translate_sort_to_meilisearch("") == []


SAMPLE_DOCS = [
    {"id": "1", "name": "Alpha", "category": "A", "price": 100, "is_active": True},
    {"id": "2", "name": "Beta", "category": "B", "price": 50, "is_active": False},
    {"id": "3", "name": "Gamma", "category": "A", "price": 200, "is_active": True},
    {"id": "4", "name": "Delta", "category": "C", "price": 75, "is_active": True},
]


class TestApplyFiltersToDocuments:
    def test_string_filter(self):
        result = apply_filters_to_documents(SAMPLE_DOCS, {"category": "A"})
        assert len(result) == 2

    def test_boolean_filter(self):
        result = apply_filters_to_documents(SAMPLE_DOCS, {"is_active": True})
        assert len(result) == 3

    def test_boolean_false_filter(self):
        result = apply_filters_to_documents(SAMPLE_DOCS, {"is_active": False})
        assert len(result) == 1

    def test_numeric_filter(self):
        result = apply_filters_to_documents(SAMPLE_DOCS, {"price": 100})
        assert len(result) == 1

    def test_list_filter(self):
        result = apply_filters_to_documents(SAMPLE_DOCS, {"category": ["A", "B"]})
        assert len(result) == 3

    def test_multiple_filters(self):
        result = apply_filters_to_documents(SAMPLE_DOCS, {"category": "A", "is_active": True})
        assert len(result) == 2

    def test_no_matches(self):
        result = apply_filters_to_documents(SAMPLE_DOCS, {"category": "Z"})
        assert len(result) == 0

    def test_empty_filter_returns_all(self):
        result = apply_filters_to_documents(SAMPLE_DOCS, {})
        assert len(result) == 4

    def test_string_filter_passthrough(self):
        result = apply_filters_to_documents(SAMPLE_DOCS, "raw string")
        assert len(result) == 4  # no filtering applied

    def test_none_value_filter(self):
        docs = [{"id": "1", "tag": None}, {"id": "2", "tag": "yes"}]
        result = apply_filters_to_documents(docs, {"tag": None})
        assert len(result) == 1
        assert result[0]["id"] == "1"


class TestApplySortToDocuments:
    def test_ascending(self):
        result = apply_sort_to_documents(SAMPLE_DOCS, ["name"])
        names = [d["name"] for d in result]
        assert names == ["Alpha", "Beta", "Delta", "Gamma"]

    def test_descending(self):
        result = apply_sort_to_documents(SAMPLE_DOCS, ["-price"])
        prices = [d["price"] for d in result]
        assert prices == [200, 100, 75, 50]

    def test_meilisearch_format(self):
        result = apply_sort_to_documents(SAMPLE_DOCS, ["price:desc"])
        prices = [d["price"] for d in result]
        assert prices == [200, 100, 75, 50]

    def test_empty_sort(self):
        result = apply_sort_to_documents(SAMPLE_DOCS, [])
        assert result == SAMPLE_DOCS

    def test_none_values_sort_last(self):
        docs = [{"id": "1", "x": "b"}, {"id": "2", "x": None}, {"id": "3", "x": "a"}]
        result = apply_sort_to_documents(docs, ["x"])
        assert [d["x"] for d in result] == ["a", "b", None]

    def test_multi_field_sort(self):
        docs = [
            {"id": "1", "category": "B", "price": 10},
            {"id": "2", "category": "A", "price": 20},
            {"id": "3", "category": "A", "price": 10},
        ]
        result = apply_sort_to_documents(docs, ["category", "price"])
        # category A first (ascending), then price ascending within category
        assert result[0]["id"] == "3"  # A, 10
        assert result[1]["id"] == "2"  # A, 20
        assert result[2]["id"] == "1"  # B, 10


class TestDummyBackendFilterSort:
    """Test that DummyBackend's search() now supports filter and sort."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from icv_search.backends.dummy import DummyBackend

        self.backend = DummyBackend()
        self.backend.create_index("products")
        self.backend.add_documents(
            "products",
            [
                {"id": "1", "name": "Padel Racket", "category": "equipment", "price": 150, "is_active": True},
                {"id": "2", "name": "Tennis Ball", "category": "accessories", "price": 10, "is_active": True},
                {"id": "3", "name": "Padel Shoes", "category": "equipment", "price": 80, "is_active": False},
                {"id": "4", "name": "Padel Grip", "category": "accessories", "price": 5, "is_active": True},
            ],
        )
        yield
        DummyBackend.reset()

    def test_filter_by_category(self):
        result = self.backend.search("products", "", filter={"category": "equipment"})
        assert result["estimatedTotalHits"] == 2

    def test_filter_by_boolean(self):
        result = self.backend.search("products", "", filter={"is_active": True})
        assert result["estimatedTotalHits"] == 3

    def test_filter_by_boolean_false(self):
        result = self.backend.search("products", "", filter={"is_active": False})
        assert result["estimatedTotalHits"] == 1

    def test_filter_combined_with_query(self):
        result = self.backend.search("products", "padel", filter={"category": "equipment"})
        assert all("Padel" in h["name"] for h in result["hits"])

    def test_sort_descending(self):
        result = self.backend.search("products", "", sort=["-price"])
        prices = [h["price"] for h in result["hits"]]
        assert prices == sorted(prices, reverse=True)

    def test_sort_ascending(self):
        result = self.backend.search("products", "", sort=["name"])
        names = [h["name"] for h in result["hits"]]
        assert names == sorted(names)

    def test_filter_and_sort_combined(self):
        result = self.backend.search("products", "", filter={"is_active": True}, sort=["-price"])
        assert result["estimatedTotalHits"] == 3
        prices = [h["price"] for h in result["hits"]]
        assert prices == sorted(prices, reverse=True)

    def test_filter_with_list_value(self):
        result = self.backend.search("products", "", filter={"category": ["equipment", "accessories"]})
        assert result["estimatedTotalHits"] == 4

    def test_no_filter_returns_all_documents(self):
        result = self.backend.search("products", "")
        assert result["estimatedTotalHits"] == 4

    def test_filter_and_query_combined_estimatedtotalhits(self):
        """estimatedTotalHits reflects the count after filtering, before pagination."""
        result = self.backend.search("products", "Padel", filter={"category": "equipment"}, limit=1)
        # 2 Padel equipment items, only 1 returned due to limit
        assert result["estimatedTotalHits"] == 2
        assert len(result["hits"]) == 1
