"""Tests for snake_case → camelCase normalisation of engine settings.

Regression coverage for the Meilisearch ``Unknown field 'ranking'`` 400 error:
``SearchIndex.settings`` historically documented snake_case keys, but the
Meilisearch settings endpoint only accepts camelCase and rejects unknown
fields.  ``normalize_engine_settings`` translates known aliases on the way out
of ``_sync_index_to_engine`` so sync stays resilient to legacy/seeded data.
"""

from icv_search.backends.dummy import _settings
from icv_search.services.indexing import (
    _sync_index_to_engine,
    create_index,
    normalize_engine_settings,
)


class TestNormalizeEngineSettings:
    """Pure-function behaviour of ``normalize_engine_settings``."""

    def test_translates_known_snake_case_keys(self):
        result = normalize_engine_settings(
            {
                "searchable_attributes": ["name"],
                "filterable_attributes": ["brand"],
                "sortable_attributes": ["price"],
                "stop_words": ["the"],
                "ranking_rules": ["words", "typo"],
            }
        )
        assert result == {
            "searchableAttributes": ["name"],
            "filterableAttributes": ["brand"],
            "sortableAttributes": ["price"],
            "stopWords": ["the"],
            "rankingRules": ["words", "typo"],
        }

    def test_bare_ranking_alias_maps_to_ranking_rules(self):
        """The bare ``ranking`` key — which triggered the original 400 — maps
        to the valid ``rankingRules`` Meilisearch setting."""
        result = normalize_engine_settings({"ranking": ["words", "typo"]})
        assert result == {"rankingRules": ["words", "typo"]}
        assert "ranking" not in result

    def test_camel_case_keys_pass_through_unchanged(self):
        settings = {
            "searchableAttributes": ["name"],
            "rankingRules": ["words"],
            "typoTolerance": {"enabled": True},
        }
        assert normalize_engine_settings(settings) == settings

    def test_unknown_keys_preserved(self):
        settings = {"someCustomEngineKey": 1, "filterableAttributes": ["x"]}
        assert normalize_engine_settings(settings) == settings

    def test_canonical_key_wins_over_alias(self):
        """When both an alias and its canonical key are present, the explicit
        camelCase value is kept and the alias is dropped."""
        result = normalize_engine_settings(
            {
                "ranking_rules": ["legacy"],
                "rankingRules": ["canonical"],
            }
        )
        assert result == {"rankingRules": ["canonical"]}

    def test_empty_settings(self):
        assert normalize_engine_settings({}) == {}

    def test_does_not_mutate_input(self):
        settings = {"ranking_rules": ["words"]}
        normalize_engine_settings(settings)
        assert settings == {"ranking_rules": ["words"]}


class TestSyncNormalisesSettings:
    """``_sync_index_to_engine`` pushes normalised camelCase keys to the engine."""

    def test_snake_case_settings_synced_as_camel_case(self, db):
        index = create_index("products")
        index.settings = {
            "searchable_attributes": ["name", "description"],
            "ranking_rules": ["words", "typo"],
        }
        index.save()

        _sync_index_to_engine(index)

        pushed = _settings[index.engine_uid]
        assert "searchable_attributes" not in pushed
        assert "ranking_rules" not in pushed
        assert pushed["searchableAttributes"] == ["name", "description"]
        assert pushed["rankingRules"] == ["words", "typo"]

    def test_bare_ranking_key_does_not_reach_engine(self, db):
        """Regression: a stored ``ranking`` key must be rewritten to
        ``rankingRules`` rather than forwarded verbatim (the original 400)."""
        index = create_index("articles")
        index.settings = {"ranking": ["words", "typo", "proximity"]}
        index.save()

        _sync_index_to_engine(index)

        pushed = _settings[index.engine_uid]
        assert "ranking" not in pushed
        assert pushed["rankingRules"] == ["words", "typo", "proximity"]
