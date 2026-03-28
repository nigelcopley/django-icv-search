"""Tests for ranking score support in SearchResult and backends."""

from __future__ import annotations

import pytest

from icv_search.types import SearchResult

# ---------------------------------------------------------------------------
# SearchResult.from_engine — ranking score extraction
# ---------------------------------------------------------------------------


class TestSearchResultRankingScores:
    """SearchResult extracts ranking scores from engine responses."""

    def test_ranking_scores_empty_by_default(self):
        """When no ranking score data is present, ranking_scores is empty."""
        result = SearchResult.from_engine({"hits": [], "query": ""})
        assert result.ranking_scores == []

    def test_ranking_scores_from_meilisearch_hits(self):
        """_rankingScore embedded on each Meilisearch hit is extracted into
        ranking_scores, and stripped from the plain hits."""
        raw = {
            "hits": [
                {"id": "1", "title": "Chair", "_rankingScore": 0.9872},
                {"id": "2", "title": "Table", "_rankingScore": 0.7654},
            ],
            "query": "chair",
        }
        result = SearchResult.from_engine(raw)

        assert result.ranking_scores == [0.9872, 0.7654]
        # _rankingScore must be stripped from plain hits
        assert "_rankingScore" not in result.hits[0]
        assert "_rankingScore" not in result.hits[1]

    def test_ranking_scores_from_top_level_key(self):
        """A top-level ranking_scores list (Postgres / Dummy) is accepted."""
        raw = {
            "hits": [{"id": "1", "title": "Chair"}, {"id": "2", "title": "Table"}],
            "query": "chair",
            "ranking_scores": [0.75, 0.50],
        }
        result = SearchResult.from_engine(raw)
        assert result.ranking_scores == [0.75, 0.50]

    def test_meilisearch_scores_take_precedence(self):
        """Per-hit _rankingScore takes precedence over a top-level list."""
        raw = {
            "hits": [{"id": "1", "_rankingScore": 0.95}],
            "query": "q",
            "ranking_scores": [0.50],  # should be ignored
        }
        result = SearchResult.from_engine(raw)
        assert result.ranking_scores == [0.95]

    def test_none_score_when_hit_has_no_ranking_score(self):
        """Hits without _rankingScore contribute to the top-level check only;
        the list is either all-from-hits or all-from-top-level."""
        raw = {
            "hits": [
                {"id": "1", "title": "A"},  # no _rankingScore
                {"id": "2", "title": "B"},  # no _rankingScore
            ],
            "query": "a",
        }
        result = SearchResult.from_engine(raw)
        assert result.ranking_scores == []

    def test_formatted_hit_not_affected(self):
        """_formatted should still be extracted even when _rankingScore is present."""
        raw = {
            "hits": [
                {
                    "id": "1",
                    "title": "Chair",
                    "_rankingScore": 0.9,
                    "_formatted": {"id": "1", "title": "<mark>Chair</mark>"},
                }
            ],
            "query": "chair",
        }
        result = SearchResult.from_engine(raw)
        assert result.ranking_scores == [0.9]
        assert result.formatted_hits == [{"id": "1", "title": "<mark>Chair</mark>"}]
        assert "_rankingScore" not in result.hits[0]
        assert "_formatted" not in result.hits[0]


# ---------------------------------------------------------------------------
# SearchResult.get_hit_with_score
# ---------------------------------------------------------------------------


class TestGetHitWithScore:
    """get_hit_with_score() returns a (hit, score) tuple."""

    def test_returns_hit_and_score(self):
        """Returns the hit at the given index paired with its score."""
        result = SearchResult(
            hits=[{"id": "1", "title": "Chair"}, {"id": "2", "title": "Table"}],
            ranking_scores=[0.95, 0.72],
        )
        hit, score = result.get_hit_with_score(0)
        assert hit == {"id": "1", "title": "Chair"}
        assert score == 0.95

    def test_second_hit_with_score(self):
        result = SearchResult(
            hits=[{"id": "1"}, {"id": "2"}],
            ranking_scores=[0.9, 0.6],
        )
        hit, score = result.get_hit_with_score(1)
        assert hit["id"] == "2"
        assert score == 0.6

    def test_returns_none_when_no_scores(self):
        """When ranking_scores is empty, score is None."""
        result = SearchResult(
            hits=[{"id": "1", "title": "Chair"}],
            ranking_scores=[],
        )
        hit, score = result.get_hit_with_score(0)
        assert hit == {"id": "1", "title": "Chair"}
        assert score is None

    def test_returns_none_when_index_beyond_scores(self):
        """When the scores list is shorter than hits, score is None."""
        result = SearchResult(
            hits=[{"id": "1"}, {"id": "2"}, {"id": "3"}],
            ranking_scores=[0.9],  # only one score
        )
        _, score = result.get_hit_with_score(2)
        assert score is None

    def test_raises_index_error_on_out_of_range_hit(self):
        """Requesting an index beyond hits should raise IndexError."""
        result = SearchResult(hits=[{"id": "1"}])
        with pytest.raises(IndexError):
            result.get_hit_with_score(5)


# ---------------------------------------------------------------------------
# DummyBackend ranking scores
# ---------------------------------------------------------------------------


class TestDummyBackendRankingScores:
    """DummyBackend computes relevance scores for query results."""

    def setup_method(self):
        from icv_search.backends.dummy import DummyBackend

        DummyBackend.reset()
        self.backend = DummyBackend()
        self.backend.create_index("test")

    def teardown_method(self):
        from icv_search.backends.dummy import DummyBackend

        DummyBackend.reset()

    def test_scores_present_for_query_matches(self):
        """ranking_scores is populated when a query is supplied."""
        self.backend.add_documents(
            "test",
            [
                {"id": "1", "title": "Python programming guide"},
                {"id": "2", "title": "Python web framework tutorial"},
            ],
        )
        result = self.backend.search("test", "python")
        assert "ranking_scores" in result
        assert len(result["ranking_scores"]) == 2

    def test_scores_not_present_for_empty_query(self):
        """No ranking_scores when the query is an empty string."""
        self.backend.add_documents("test", [{"id": "1", "title": "Hello"}])
        result = self.backend.search("test", "")
        assert "ranking_scores" not in result

    def test_scores_are_floats(self):
        """Scores must be numeric (float or int)."""
        self.backend.add_documents("test", [{"id": "1", "title": "Python language"}])
        result = self.backend.search("test", "python")
        for score in result.get("ranking_scores", []):
            assert isinstance(score, (int, float))

    def test_scores_between_zero_and_one(self):
        """Scores are capped at 1.0 and non-negative."""
        self.backend.add_documents(
            "test",
            [{"id": "1", "title": "match match match match match match match match"}],
        )
        result = self.backend.search("test", "match")
        for score in result.get("ranking_scores", []):
            assert 0.0 <= score <= 1.0

    def test_scores_accessible_via_search_result(self):
        """SearchResult.from_engine picks up Dummy's ranking_scores."""
        self.backend.add_documents("test", [{"id": "1", "title": "Chair design"}])
        raw = self.backend.search("test", "chair")
        result = SearchResult.from_engine(raw)
        assert len(result.ranking_scores) == 1
        assert result.ranking_scores[0] is not None

    def test_no_scores_when_no_results(self):
        """Empty results produce no ranking_scores entry."""
        result = self.backend.search("test", "nonexistent")
        assert result.get("ranking_scores", []) == []


# ---------------------------------------------------------------------------
# SearchResult.from_engine — no scores (backward compat)
# ---------------------------------------------------------------------------


class TestSearchResultBackwardCompat:
    """Existing callers that don't send ranking score data still work."""

    def test_from_engine_without_scores_field(self):
        """A response dict without any score data produces an empty list."""
        raw = {
            "hits": [{"id": "1", "title": "Chair"}],
            "query": "chair",
            "processingTimeMs": 5,
            "estimatedTotalHits": 1,
        }
        result = SearchResult.from_engine(raw)
        assert result.ranking_scores == []
        assert len(result.hits) == 1

    def test_hits_are_clean_without_score_stripping(self):
        """Hits from backends that don't embed _rankingScore remain unmodified."""
        raw = {
            "hits": [{"id": "1", "title": "Widget", "category": "tools"}],
            "query": "widget",
        }
        result = SearchResult.from_engine(raw)
        assert result.hits[0] == {"id": "1", "title": "Widget", "category": "tools"}
