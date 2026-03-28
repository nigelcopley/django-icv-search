"""Integration tests for the merchandised_search pipeline."""

import pytest

from icv_search.backends.dummy import DummyBackend
from icv_search.models import SearchIndex
from icv_search.models.merchandising import (
    BoostRule,
    QueryRedirect,
    QueryRewrite,
    SearchBanner,
    SearchPin,
    ZeroResultFallback,
)
from icv_search.services.merchandising import merchandised_search
from icv_search.types import MerchandisedSearchResult


@pytest.fixture(autouse=True)
def _merch_settings(settings):
    settings.ICV_SEARCH_MERCHANDISING_ENABLED = True
    settings.ICV_SEARCH_MERCHANDISING_CACHE_TIMEOUT = 0


@pytest.fixture
def products_index(db):
    index = SearchIndex.objects.create(name="products", tenant_id="", primary_key_field="id")
    backend = DummyBackend()
    backend.create_index(index.engine_uid, primary_key="id")
    backend.add_documents(
        index.engine_uid,
        [
            {"id": "1", "name": "Red Shoes", "category": "footwear", "price": 50},
            {"id": "2", "name": "Blue Shirt", "category": "clothing", "price": 30},
            {"id": "3", "name": "Green Hat", "category": "accessories", "price": 20},
            {"id": "4", "name": "Red Dress", "category": "clothing", "price": 80},
            {"id": "5", "name": "Red Bag", "category": "accessories", "price": 45},
        ],
    )
    return index


class TestMerchandisingDisabled:
    """When ICV_SEARCH_MERCHANDISING_ENABLED is False, pipeline is a passthrough."""

    def test_returns_merchandised_search_result(self, products_index, settings):
        settings.ICV_SEARCH_MERCHANDISING_ENABLED = False
        result = merchandised_search("products", "red")
        assert isinstance(result, MerchandisedSearchResult)
        assert len(result.hits) > 0

    def test_no_rules_evaluated(self, products_index, settings):
        settings.ICV_SEARCH_MERCHANDISING_ENABLED = False
        QueryRedirect.objects.create(
            index_name="products",
            query_pattern="red",
            match_type="exact",
            destination_url="https://example.com/red",
        )
        result = merchandised_search("products", "red")
        assert result.redirect is None
        assert result.applied_rules == []

    def test_original_query_preserved(self, products_index, settings):
        settings.ICV_SEARCH_MERCHANDISING_ENABLED = False
        result = merchandised_search("products", "red")
        assert result.original_query == "red"


class TestRedirectShortCircuit:
    """Step 3: redirect check short-circuits the pipeline."""

    def test_redirect_returns_url(self, products_index):
        QueryRedirect.objects.create(
            index_name="products",
            query_pattern="sale",
            match_type="exact",
            destination_url="https://example.com/sale",
            http_status=302,
        )
        result = merchandised_search("products", "sale")
        assert result.redirect is not None
        assert result.redirect["url"] == "https://example.com/sale"
        assert result.redirect["status"] == 302
        assert result.hits == []

    def test_redirect_populates_applied_rules(self, products_index):
        QueryRedirect.objects.create(
            index_name="products",
            query_pattern="sale",
            match_type="exact",
            destination_url="https://example.com/sale",
        )
        result = merchandised_search("products", "sale")
        redirect_rules = [r for r in result.applied_rules if r["type"] == "redirect"]
        assert len(redirect_rules) == 1

    def test_skip_redirects_bypasses_redirect(self, products_index):
        QueryRedirect.objects.create(
            index_name="products",
            query_pattern="red",
            match_type="exact",
            destination_url="https://example.com/red",
        )
        result = merchandised_search("products", "red", skip_redirects=True)
        assert result.redirect is None
        assert len(result.hits) > 0


class TestRewriteStep:
    """Step 4: query rewrite modifies the search query."""

    def test_rewrite_changes_query(self, products_index):
        QueryRewrite.objects.create(
            index_name="products",
            query_pattern="sneakers",
            match_type="exact",
            rewritten_query="shoes",
        )
        result = merchandised_search("products", "sneakers")
        assert result.was_rewritten is True
        assert result.original_query == "sneakers"
        # Should find "Red Shoes" because query was rewritten to "shoes"
        assert len(result.hits) > 0

    def test_rewrite_merges_filters(self, products_index):
        QueryRewrite.objects.create(
            index_name="products",
            query_pattern="cheap shoes",
            match_type="exact",
            rewritten_query="shoes",
            apply_filters={"category": "footwear"},
            merge_filters=True,
        )
        result = merchandised_search("products", "cheap shoes")
        assert result.was_rewritten is True
        assert any(r["type"] == "rewrite" for r in result.applied_rules)

    def test_skip_rewrites_bypasses(self, products_index):
        QueryRewrite.objects.create(
            index_name="products",
            query_pattern="sneakers",
            match_type="exact",
            rewritten_query="shoes",
        )
        result = merchandised_search("products", "sneakers", skip_rewrites=True)
        assert result.was_rewritten is False


class TestPinStep:
    """Step 6: pin insertion after search."""

    def test_pin_inserts_document_at_position(self, products_index):
        SearchPin.objects.create(
            index_name="products",
            query_pattern="red",
            match_type="exact",
            document_id="3",  # Green Hat - not normally in "red" results
            position=0,
        )
        result = merchandised_search("products", "red")
        # The pinned document should be at position 0
        assert result.hits[0]["id"] == "3"
        assert result.hits[0].get("_pinned") is True

    def test_pin_applied_rules_populated(self, products_index):
        SearchPin.objects.create(
            index_name="products",
            query_pattern="red",
            match_type="exact",
            document_id="3",
            position=0,
        )
        result = merchandised_search("products", "red")
        pin_rules = [r for r in result.applied_rules if r["type"] == "pin"]
        assert len(pin_rules) == 1
        assert pin_rules[0]["document_id"] == "3"

    def test_skip_pins_bypasses(self, products_index):
        SearchPin.objects.create(
            index_name="products",
            query_pattern="red",
            match_type="exact",
            document_id="3",
            position=0,
        )
        result = merchandised_search("products", "red", skip_pins=True)
        pin_rules = [r for r in result.applied_rules if r["type"] == "pin"]
        assert len(pin_rules) == 0


class TestBoostStep:
    """Step 7: boost re-ranking after pins."""

    def test_boost_promotes_document(self, products_index):
        BoostRule.objects.create(
            index_name="products",
            query_pattern="red",
            match_type="exact",
            field="category",
            field_value="accessories",
            operator="eq",
            boost_weight=10.0,
        )
        result = merchandised_search("products", "red")
        # Red Bag (accessories) should be promoted
        assert any(r["type"] == "boost" for r in result.applied_rules)

    def test_skip_boosts_bypasses(self, products_index):
        BoostRule.objects.create(
            index_name="products",
            query_pattern="red",
            match_type="exact",
            field="category",
            field_value="accessories",
            operator="eq",
            boost_weight=10.0,
        )
        result = merchandised_search("products", "red", skip_boosts=True)
        boost_rules = [r for r in result.applied_rules if r["type"] == "boost"]
        assert len(boost_rules) == 0


class TestFallbackStep:
    """Step 8: zero-result fallback."""

    def test_fallback_on_zero_results(self, products_index):
        ZeroResultFallback.objects.create(
            index_name="products",
            query_pattern="xyznonexistent",
            match_type="exact",
            fallback_type="alternative_query",
            fallback_value="red",
        )
        result = merchandised_search("products", "xyznonexistent")
        assert result.is_fallback is True
        assert result.original_query == "xyznonexistent"
        # Fallback should have found "red" items
        assert len(result.hits) > 0

    def test_fallback_redirect_type(self, products_index):
        ZeroResultFallback.objects.create(
            index_name="products",
            query_pattern="xyznonexistent",
            match_type="exact",
            fallback_type="redirect",
            fallback_value="https://example.com/browse",
        )
        result = merchandised_search("products", "xyznonexistent")
        assert result.redirect is not None
        assert result.redirect["url"] == "https://example.com/browse"
        assert result.is_fallback is True

    def test_skip_fallbacks_bypasses(self, products_index):
        ZeroResultFallback.objects.create(
            index_name="products",
            query_pattern="xyznonexistent",
            match_type="exact",
            fallback_type="alternative_query",
            fallback_value="red",
        )
        result = merchandised_search("products", "xyznonexistent", skip_fallbacks=True)
        assert result.is_fallback is False
        assert len(result.hits) == 0

    def test_no_fallback_when_results_exist(self, products_index):
        ZeroResultFallback.objects.create(
            index_name="products",
            query_pattern="red",
            match_type="exact",
            fallback_type="alternative_query",
            fallback_value="blue",
        )
        result = merchandised_search("products", "red")
        assert result.is_fallback is False


class TestBannerStep:
    """Step 9: banner attachment."""

    def test_banner_attached(self, products_index):
        SearchBanner.objects.create(
            index_name="products",
            query_pattern="red",
            match_type="exact",
            title="Red Sale!",
            content="50% off all red items",
            position="top",
            banner_type="promotional",
        )
        result = merchandised_search("products", "red")
        assert len(result.banners) == 1
        assert result.banners[0]["title"] == "Red Sale!"
        assert result.banners[0]["position"] == "top"

    def test_multiple_banners(self, products_index):
        SearchBanner.objects.create(
            index_name="products",
            query_pattern="red",
            match_type="exact",
            title="Banner 1",
            position="top",
        )
        SearchBanner.objects.create(
            index_name="products",
            query_pattern="red",
            match_type="exact",
            title="Banner 2",
            position="bottom",
        )
        result = merchandised_search("products", "red")
        assert len(result.banners) == 2

    def test_skip_banners_bypasses(self, products_index):
        SearchBanner.objects.create(
            index_name="products",
            query_pattern="red",
            match_type="exact",
            title="Red Sale!",
        )
        result = merchandised_search("products", "red", skip_banners=True)
        assert len(result.banners) == 0


class TestFullPipeline:
    """End-to-end tests combining multiple pipeline steps."""

    def test_rewrite_then_pins_then_boosts_then_banners(self, products_index):
        """Full pipeline: rewrite + pin + boost + banner in one query."""
        QueryRewrite.objects.create(
            index_name="products",
            query_pattern="trainers",
            match_type="exact",
            rewritten_query="shoes",
        )
        SearchPin.objects.create(
            index_name="products",
            query_pattern="trainers",
            match_type="exact",
            document_id="3",
            position=0,
            label="editorial pick",
        )
        BoostRule.objects.create(
            index_name="products",
            query_pattern="trainers",
            match_type="exact",
            field="price",
            field_value="50",
            operator="lte",
            boost_weight=2.0,
        )
        SearchBanner.objects.create(
            index_name="products",
            query_pattern="trainers",
            match_type="exact",
            title="Trainer Season",
            position="top",
        )
        result = merchandised_search("products", "trainers")

        assert isinstance(result, MerchandisedSearchResult)
        assert result.was_rewritten is True
        assert result.original_query == "trainers"
        assert len(result.banners) == 1
        assert result.banners[0]["title"] == "Trainer Season"

        rule_types = [r["type"] for r in result.applied_rules]
        assert "rewrite" in rule_types
        assert "pin" in rule_types
        assert "boost" in rule_types
        assert "banner" in rule_types

    def test_redirect_prevents_search(self, products_index):
        """Redirect at step 3 prevents steps 4-9 from running."""
        QueryRedirect.objects.create(
            index_name="products",
            query_pattern="special",
            match_type="exact",
            destination_url="https://example.com/special",
        )
        # Also add other rules that should NOT be triggered
        SearchBanner.objects.create(
            index_name="products",
            query_pattern="special",
            match_type="exact",
            title="Should not appear",
        )
        result = merchandised_search("products", "special")
        assert result.redirect is not None
        assert len(result.banners) == 0
        assert len(result.hits) == 0

    def test_query_normalisation(self, products_index):
        """Queries are normalised (stripped, lowered) before rule matching."""
        QueryRedirect.objects.create(
            index_name="products",
            query_pattern="sale",
            match_type="exact",
            destination_url="https://example.com/sale",
        )
        result = merchandised_search("products", "  SALE  ")
        assert result.redirect is not None

    def test_applied_rules_order(self, products_index):
        """Applied rules list reflects pipeline execution order."""
        QueryRewrite.objects.create(
            index_name="products",
            query_pattern="red",
            match_type="exact",
            rewritten_query="red",
        )
        SearchPin.objects.create(
            index_name="products",
            query_pattern="red",
            match_type="exact",
            document_id="99",
            position=0,
        )
        SearchBanner.objects.create(
            index_name="products",
            query_pattern="red",
            match_type="exact",
            title="Red Banner",
        )
        result = merchandised_search("products", "red")
        rule_types = [r["type"] for r in result.applied_rules]
        # Order: preprocess, rewrite, pin, banner (no boost because no BoostRule created)
        preprocess_idx = rule_types.index("preprocess")
        rewrite_idx = rule_types.index("rewrite")
        pin_idx = rule_types.index("pin")
        banner_idx = rule_types.index("banner")
        assert preprocess_idx < rewrite_idx < pin_idx < banner_idx
