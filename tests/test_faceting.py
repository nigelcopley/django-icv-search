"""Tests for facet distribution support in DummyBackend and SearchResult."""

from __future__ import annotations

from icv_search.backends.dummy import DummyBackend
from icv_search.types import SearchResult


class TestDummyBackendFacets:
    """DummyBackend facet distribution computation."""

    def setup_method(self):
        DummyBackend.reset()
        self.backend = DummyBackend()
        self.backend.create_index("products")
        self.backend.add_documents(
            "products",
            [
                {"id": "1", "name": "Running Shoe A", "category": "footwear", "brand": "Nike"},
                {"id": "2", "name": "Running Shoe B", "category": "footwear", "brand": "Adidas"},
                {"id": "3", "name": "Laptop Stand", "category": "electronics", "brand": "Nike"},
                {"id": "4", "name": "Wireless Keyboard", "category": "electronics", "brand": "Logitech"},
                {"id": "5", "name": "USB-C Hub", "category": "electronics", "brand": "Logitech"},
            ],
        )

    def test_single_facet_returns_correct_counts(self):
        result = self.backend.search("products", "", facets=["category"])

        distribution = result["facetDistribution"]
        assert distribution["category"]["electronics"] == 3
        assert distribution["category"]["footwear"] == 2

    def test_multiple_facets_returned_together(self):
        result = self.backend.search("products", "", facets=["category", "brand"])

        distribution = result["facetDistribution"]
        assert "category" in distribution
        assert "brand" in distribution
        assert distribution["brand"]["Nike"] == 2
        assert distribution["brand"]["Adidas"] == 1
        assert distribution["brand"]["Logitech"] == 2

    def test_facets_reflect_query_filter(self):
        """Facet counts should be computed over matched docs only, not the full index."""
        result = self.backend.search("products", "Running", facets=["category", "brand"])

        distribution = result["facetDistribution"]
        # Only "Running Shoe A" and "Running Shoe B" match the query
        assert distribution["category"] == {"footwear": 2}
        assert distribution["brand"] == {"Nike": 1, "Adidas": 1}

    def test_facets_reflect_applied_filters(self):
        """Facet counts should be computed over filtered docs only."""
        result = self.backend.search(
            "products",
            "",
            filter={"category": "electronics"},
            facets=["brand"],
        )

        distribution = result["facetDistribution"]
        # Only electronics docs: ids 3, 4, 5
        assert distribution["brand"]["Nike"] == 1
        assert distribution["brand"]["Logitech"] == 2
        assert "Adidas" not in distribution["brand"]

    def test_faceting_empty_result_set(self):
        """When no documents match, all facet dists should be empty."""
        result = self.backend.search("products", "zzz_no_match", facets=["category", "brand"])

        assert result["facetDistribution"]["category"] == {}
        assert result["facetDistribution"]["brand"] == {}

    def test_faceting_missing_field_skips_document(self):
        """Documents that lack the facet field are excluded from the count."""
        DummyBackend.reset()
        backend = DummyBackend()
        backend.create_index("mixed")
        backend.add_documents(
            "mixed",
            [
                {"id": "1", "title": "Article A", "tag": "news"},
                {"id": "2", "title": "Article B", "tag": "sports"},
                {"id": "3", "title": "Article C"},  # no "tag" field
            ],
        )

        result = backend.search("mixed", "", facets=["tag"])

        distribution = result["facetDistribution"]["tag"]
        assert distribution == {"news": 1, "sports": 1}

    def test_facets_absent_when_not_requested(self):
        """When facets param is omitted the response should not include facetDistribution."""
        result = self.backend.search("products", "")

        assert "facetDistribution" not in result

    def test_facets_with_pagination_counts_all_matched_docs(self):
        """Facet totals reflect all matched documents, not just the current page."""
        result = self.backend.search("products", "", limit=1, offset=0, facets=["category"])

        # Only 1 hit returned but all 5 docs should contribute to facet counts
        assert len(result["hits"]) == 1
        assert result["facetDistribution"]["category"]["electronics"] == 3
        assert result["facetDistribution"]["category"]["footwear"] == 2

    def test_facets_empty_list_behaves_as_not_requested(self):
        """Passing an empty list for facets should not include facetDistribution."""
        result = self.backend.search("products", "", facets=[])

        assert "facetDistribution" not in result

    def test_unknown_facet_field_returns_empty_distribution(self):
        """A facet field not present in any document yields an empty dict, not an error."""
        result = self.backend.search("products", "", facets=["nonexistent_field"])

        assert result["facetDistribution"]["nonexistent_field"] == {}


class TestSearchResultFacetDistribution:
    """SearchResult.from_engine() and get_facet_values() with facet data."""

    def _make_engine_response(self, facet_distribution: dict) -> dict:
        return {
            "hits": [],
            "query": "test",
            "processingTimeMs": 5,
            "estimatedTotalHits": 0,
            "limit": 20,
            "offset": 0,
            "facetDistribution": facet_distribution,
        }

    def test_from_engine_populates_facet_distribution(self):
        data = self._make_engine_response({"category": {"electronics": 5, "books": 3}})

        result = SearchResult.from_engine(data)

        assert result.facet_distribution == {"category": {"electronics": 5, "books": 3}}

    def test_from_engine_accepts_snake_case_key(self):
        """SearchResult should accept both camelCase and snake_case keys."""
        data = {
            "hits": [],
            "query": "",
            "processingTimeMs": 0,
            "estimatedTotalHits": 0,
            "facet_distribution": {"brand": {"Nike": 2}},
        }

        result = SearchResult.from_engine(data)

        assert result.facet_distribution == {"brand": {"Nike": 2}}

    def test_from_engine_defaults_to_empty_dict_when_absent(self):
        data = {
            "hits": [],
            "query": "",
            "processingTimeMs": 0,
            "estimatedTotalHits": 0,
        }

        result = SearchResult.from_engine(data)

        assert result.facet_distribution == {}

    def test_get_facet_values_sorted_by_count_descending(self):
        data = self._make_engine_response({"category": {"books": 3, "electronics": 5, "toys": 1}})
        result = SearchResult.from_engine(data)

        values = result.get_facet_values("category")

        assert values[0] == {"name": "electronics", "count": 5}
        assert values[1] == {"name": "books", "count": 3}
        assert values[2] == {"name": "toys", "count": 1}

    def test_get_facet_values_unknown_facet_returns_empty_list(self):
        result = SearchResult.from_engine(self._make_engine_response({}))

        assert result.get_facet_values("nonexistent") == []

    def test_facet_distribution_roundtrip_via_dummy_backend(self):
        """End-to-end: DummyBackend produces a response that SearchResult parses correctly."""
        DummyBackend.reset()
        backend = DummyBackend()
        backend.create_index("items")
        backend.add_documents(
            "items",
            [
                {"id": "1", "colour": "red"},
                {"id": "2", "colour": "blue"},
                {"id": "3", "colour": "red"},
            ],
        )

        raw = backend.search("items", "", facets=["colour"])
        result = SearchResult.from_engine(raw)

        assert result.facet_distribution == {"colour": {"red": 2, "blue": 1}}
        values = result.get_facet_values("colour")
        assert values[0] == {"name": "red", "count": 2}
        assert values[1] == {"name": "blue", "count": 1}
