"""Tests for the search pin service functions."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from icv_search.models.merchandising import SearchPin
from icv_search.services.pins import apply_pins, get_pins_for_query
from icv_search.types import SearchResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pin(**kwargs) -> SearchPin:
    """Create and save a SearchPin with sensible defaults."""
    defaults = {
        "index_name": "products",
        "tenant_id": "",
        "query_pattern": "shoes",
        "match_type": "exact",
        "document_id": "42",
        "position": 0,
        "label": "",
        "is_active": True,
        "priority": 0,
    }
    defaults.update(kwargs)
    return SearchPin.objects.create(**defaults)


def _make_result(
    hits: list | None = None,
    query: str = "shoes",
    estimated_total_hits: int | None = None,
    ranking_scores: list | None = None,
) -> SearchResult:
    """Build a SearchResult for use in apply_pins() tests."""
    if hits is None:
        hits = [
            {"id": "1", "name": "Product A"},
            {"id": "2", "name": "Product B"},
            {"id": "3", "name": "Product C"},
        ]
    return SearchResult(
        hits=hits,
        query=query,
        estimated_total_hits=estimated_total_hits if estimated_total_hits is not None else len(hits),
        ranking_scores=ranking_scores or [],
    )


# ---------------------------------------------------------------------------
# get_pins_for_query()
# ---------------------------------------------------------------------------


class TestGetPinsForQuery:
    """get_pins_for_query() — rule matching and sort order."""

    @pytest.mark.django_db
    def test_returns_matching_pins(self):
        pin = _make_pin(document_id="10", position=1)
        result = get_pins_for_query("products", "shoes")
        assert len(result) == 1
        assert result[0].pk == pin.pk

    @pytest.mark.django_db
    def test_returns_empty_list_when_no_match(self):
        _make_pin(query_pattern="boots", match_type="exact")
        result = get_pins_for_query("products", "shoes")
        assert result == []

    @pytest.mark.django_db
    def test_pins_sorted_by_position_ascending(self):
        _make_pin(document_id="a", position=2)
        _make_pin(document_id="b", position=0)
        _make_pin(document_id="c", position=1)
        pins = get_pins_for_query("products", "shoes")
        positions = [p.position for p in pins]
        assert positions == [0, 1, 2]

    @pytest.mark.django_db
    def test_bury_pin_comes_last(self):
        _make_pin(document_id="a", position=0)
        _make_pin(document_id="b", position=-1)
        _make_pin(document_id="c", position=1)
        pins = get_pins_for_query("products", "shoes")
        assert pins[-1].position == -1

    @pytest.mark.django_db
    def test_inactive_pin_is_not_returned(self):
        _make_pin(document_id="99", is_active=False)
        result = get_pins_for_query("products", "shoes")
        assert result == []

    @pytest.mark.django_db
    def test_pin_scheduled_in_future_is_not_returned(self):
        _make_pin(
            document_id="99",
            starts_at=timezone.now() + timedelta(hours=1),
        )
        result = get_pins_for_query("products", "shoes")
        assert result == []

    @pytest.mark.django_db
    def test_pin_past_end_date_is_not_returned(self):
        _make_pin(
            document_id="99",
            ends_at=timezone.now() - timedelta(hours=1),
        )
        result = get_pins_for_query("products", "shoes")
        assert result == []

    @pytest.mark.django_db
    def test_pin_within_schedule_window_is_returned(self):
        pin = _make_pin(
            document_id="99",
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(hours=1),
        )
        result = get_pins_for_query("products", "shoes")
        assert len(result) == 1
        assert result[0].pk == pin.pk

    @pytest.mark.django_db
    def test_tenant_scoped_pin_matches_same_tenant(self):
        pin = _make_pin(document_id="5", tenant_id="acme")
        result = get_pins_for_query("products", "shoes", tenant_id="acme")
        assert len(result) == 1
        assert result[0].pk == pin.pk

    @pytest.mark.django_db
    def test_tenant_scoped_pin_does_not_match_other_tenant(self):
        _make_pin(document_id="5", tenant_id="acme")
        result = get_pins_for_query("products", "shoes", tenant_id="other")
        assert result == []

    @pytest.mark.django_db
    def test_global_pin_matches_when_tenant_provided(self):
        """A pin with blank tenant_id applies to all tenants."""
        pin = _make_pin(document_id="5", tenant_id="")
        result = get_pins_for_query("products", "shoes", tenant_id="acme")
        assert len(result) == 1
        assert result[0].pk == pin.pk


# ---------------------------------------------------------------------------
# apply_pins()
# ---------------------------------------------------------------------------


class TestApplyPinsNoOp:
    """apply_pins() returns the original result unchanged when there are no pins."""

    def test_empty_pins_returns_same_result(self):
        result = _make_result()
        out = apply_pins(result, [])
        assert out.hits == result.hits
        assert out.estimated_total_hits == result.estimated_total_hits

    def test_returned_result_is_new_instance_when_pins_present(self):
        """apply_pins must not mutate the original result."""
        pin = SearchPin(
            document_id="1",
            position=0,
            label="",
            index_name="products",
            query_pattern="shoes",
        )
        result = _make_result()
        out = apply_pins(result, [pin])
        assert out is not result


class TestApplyPinsInsert:
    """apply_pins() — inserting pinned documents at target positions."""

    def test_inserts_existing_document_at_position_zero(self):
        pin = SearchPin(document_id="3", position=0, label="", index_name="products", query_pattern="shoes")
        result = _make_result()
        out = apply_pins(result, [pin])
        assert out.hits[0]["id"] == "3"

    def test_inserts_existing_document_at_position_two(self):
        pin = SearchPin(document_id="1", position=2, label="", index_name="products", query_pattern="shoes")
        result = _make_result()
        out = apply_pins(result, [pin])
        assert out.hits[2]["id"] == "1"

    def test_buries_existing_document_at_end(self):
        pin = SearchPin(document_id="1", position=-1, label="", index_name="products", query_pattern="shoes")
        result = _make_result()
        out = apply_pins(result, [pin])
        assert out.hits[-1]["id"] == "1"

    def test_moves_existing_hit_rather_than_duplicating(self):
        """A document already in the result set must appear exactly once."""
        pin = SearchPin(document_id="3", position=0, label="", index_name="products", query_pattern="shoes")
        result = _make_result()
        out = apply_pins(result, [pin])
        ids = [h["id"] for h in out.hits]
        assert ids.count("3") == 1

    def test_stub_inserted_when_document_not_in_results(self):
        pin = SearchPin(document_id="99", position=0, label="", index_name="products", query_pattern="shoes")
        result = _make_result()
        out = apply_pins(result, [pin])
        assert out.hits[0]["id"] == "99"
        assert out.hits[0]["_pinned"] is True

    def test_stub_has_no_extra_fields_beyond_id_and_pinned(self):
        """Stub documents must only carry ``id`` and ``_pinned``."""
        pin = SearchPin(document_id="99", position=0, label="", index_name="products", query_pattern="shoes")
        result = _make_result()
        out = apply_pins(result, [pin])
        stub = out.hits[0]
        assert set(stub.keys()) == {"id", "_pinned"}

    def test_existing_document_marked_pinned(self):
        pin = SearchPin(document_id="2", position=0, label="", index_name="products", query_pattern="shoes")
        result = _make_result()
        out = apply_pins(result, [pin])
        pinned_hit = next(h for h in out.hits if h["id"] == "2")
        assert pinned_hit["_pinned"] is True


class TestApplyPinsEstimatedTotalHits:
    """apply_pins() — estimated_total_hits adjustment."""

    def test_adjusts_estimated_total_hits_when_stub_added(self):
        pin = SearchPin(document_id="99", position=0, label="", index_name="products", query_pattern="shoes")
        result = _make_result()
        out = apply_pins(result, [pin])
        assert out.estimated_total_hits == result.estimated_total_hits + 1

    def test_does_not_adjust_estimated_total_hits_when_moving_existing_doc(self):
        pin = SearchPin(document_id="2", position=0, label="", index_name="products", query_pattern="shoes")
        result = _make_result()
        out = apply_pins(result, [pin])
        assert out.estimated_total_hits == result.estimated_total_hits


class TestApplyPinsLabel:
    """apply_pins() — pin label attachment."""

    def test_label_attached_to_pinned_document(self):
        pin = SearchPin(document_id="1", position=0, label="sponsored", index_name="products", query_pattern="shoes")
        result = _make_result()
        out = apply_pins(result, [pin])
        pinned_hit = next(h for h in out.hits if h["id"] == "1")
        assert pinned_hit.get("_pin_label") == "sponsored"

    def test_empty_label_not_attached(self):
        pin = SearchPin(document_id="1", position=0, label="", index_name="products", query_pattern="shoes")
        result = _make_result()
        out = apply_pins(result, [pin])
        pinned_hit = next(h for h in out.hits if h["id"] == "1")
        assert "_pin_label" not in pinned_hit


class TestApplyPinsMultiple:
    """apply_pins() — multiple pins applied in order."""

    def test_multiple_pins_applied_in_sorted_order(self):
        pins = [
            SearchPin(document_id="3", position=0, label="", index_name="products", query_pattern="shoes"),
            SearchPin(document_id="2", position=1, label="", index_name="products", query_pattern="shoes"),
        ]
        result = _make_result()
        out = apply_pins(result, pins)
        assert out.hits[0]["id"] == "3"
        assert out.hits[1]["id"] == "2"

    def test_position_conflict_two_pins_same_position(self):
        """When two pins target the same position the second is inserted after the first."""
        pins = [
            SearchPin(document_id="2", position=0, label="", index_name="products", query_pattern="shoes"),
            SearchPin(document_id="3", position=0, label="", index_name="products", query_pattern="shoes"),
        ]
        result = _make_result()
        out = apply_pins(result, pins)
        # Both must be present; second pin is at position 0 again, pushing the first to 1.
        ids_at_start = [h["id"] for h in out.hits[:2]]
        assert "2" in ids_at_start
        assert "3" in ids_at_start

    def test_two_new_stub_documents_adjust_estimated_total_by_two(self):
        pins = [
            SearchPin(document_id="98", position=0, label="", index_name="products", query_pattern="shoes"),
            SearchPin(document_id="99", position=1, label="", index_name="products", query_pattern="shoes"),
        ]
        result = _make_result()
        out = apply_pins(result, pins)
        assert out.estimated_total_hits == result.estimated_total_hits + 2


class TestApplyPinsRankingScores:
    """apply_pins() preserves and adjusts ranking_scores in parallel with hits."""

    def test_ranking_scores_list_preserved_for_moved_document(self):
        pins = [
            SearchPin(document_id="3", position=0, label="", index_name="products", query_pattern="shoes"),
        ]
        result = _make_result(ranking_scores=[0.9, 0.8, 0.7])
        out = apply_pins(result, pins)
        # "3" was at index 2 with score 0.7; it should be at index 0 now.
        assert out.ranking_scores[0] == 0.7

    def test_stub_document_has_none_score(self):
        pins = [
            SearchPin(document_id="99", position=0, label="", index_name="products", query_pattern="shoes"),
        ]
        result = _make_result(ranking_scores=[0.9, 0.8, 0.7])
        out = apply_pins(result, pins)
        assert out.ranking_scores[0] is None

    def test_empty_ranking_scores_stays_empty_after_existing_doc_moved(self):
        pins = [
            SearchPin(document_id="2", position=0, label="", index_name="products", query_pattern="shoes"),
        ]
        result = _make_result(ranking_scores=[])
        out = apply_pins(result, pins)
        assert out.ranking_scores == []
