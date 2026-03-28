"""Tests for geo-distance search support.

Covers:
- Haversine distance calculation helper
- DummyBackend geo radius filtering
- DummyBackend geo distance sorting (asc/desc)
- ``_geoDistance`` present in results
- Documents without ``_geo`` field excluded from geo filter
- Meilisearch backend geo filter/sort expression construction
- SearchableMixin ``search_geo_field``, ``search_lat_field``, ``search_lng_field``
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from icv_search.backends.dummy import DummyBackend
from icv_search.backends.filters import _haversine_distance
from icv_search.backends.meilisearch import MeilisearchBackend
from icv_search.types import SearchResult

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def backend() -> DummyBackend:
    """Return a fresh DummyBackend with the standard test index."""
    b = DummyBackend()
    b.create_index("places")
    return b


@pytest.fixture()
def geo_docs(backend: DummyBackend) -> list[dict]:
    """Index three documents with varying distances from a central point.

    Reference point: Madrid (40.4168, -3.7038)

    - doc "1": Madrid city centre (~0 m)
    - doc "2": Salamanca (~200 km)
    - doc "3": Barcelona (~500 km)
    - doc "4": no _geo field — always excluded from radius filters
    """
    docs = [
        {"id": "1", "name": "Madrid", "_geo": {"lat": 40.4168, "lng": -3.7038}},
        {"id": "2", "name": "Salamanca", "_geo": {"lat": 40.9701, "lng": -5.6635}},
        {"id": "3", "name": "Barcelona", "_geo": {"lat": 41.3851, "lng": 2.1734}},
        {"id": "4", "name": "NoGeo"},
    ]
    backend.add_documents("places", docs)
    return docs


# ---------------------------------------------------------------------------
# Haversine distance helper
# ---------------------------------------------------------------------------


class TestHaversineDistance:
    """Tests for the _haversine_distance helper function."""

    def test_same_point_is_zero(self):
        dist = _haversine_distance(40.4168, -3.7038, 40.4168, -3.7038)
        assert dist == pytest.approx(0.0, abs=1e-6)

    def test_known_distance_madrid_barcelona(self):
        # Straight-line distance Madrid → Barcelona is approximately 505 km.
        dist = _haversine_distance(40.4168, -3.7038, 41.3851, 2.1734)
        assert pytest.approx(dist, rel=0.01) == 505_000

    def test_known_distance_madrid_salamanca(self):
        # Madrid → Salamanca is approximately 176 km (straight-line).
        dist = _haversine_distance(40.4168, -3.7038, 40.9701, -5.6635)
        assert pytest.approx(dist, rel=0.02) == 176_000

    def test_symmetric(self):
        """Distance A→B equals distance B→A."""
        d1 = _haversine_distance(40.4168, -3.7038, 41.3851, 2.1734)
        d2 = _haversine_distance(41.3851, 2.1734, 40.4168, -3.7038)
        assert d1 == pytest.approx(d2, rel=1e-9)

    def test_returns_float(self):
        dist = _haversine_distance(51.5074, -0.1278, 48.8566, 2.3522)
        assert isinstance(dist, float)

    @pytest.mark.parametrize(
        "lat1,lng1,lat2,lng2,expected_km",
        [
            # London → Paris ~341 km
            (51.5074, -0.1278, 48.8566, 2.3522, 341),
            # New York → Los Angeles ~3940 km
            (40.7128, -74.0060, 34.0522, -118.2437, 3940),
        ],
    )
    def test_parametrised_known_routes(self, lat1, lng1, lat2, lng2, expected_km):
        dist_km = _haversine_distance(lat1, lng1, lat2, lng2) / 1000
        assert pytest.approx(dist_km, rel=0.02) == expected_km


# ---------------------------------------------------------------------------
# DummyBackend — geo radius filtering
# ---------------------------------------------------------------------------


class TestDummyBackendGeoRadiusFilter:
    """DummyBackend filters documents by geo radius."""

    def test_radius_includes_nearby_document(self, backend, geo_docs):
        # 300 km radius from Madrid should include Madrid and Salamanca.
        result = backend.search("places", "", geo_point=(40.4168, -3.7038), geo_radius=300_000)
        ids = {h["id"] for h in result["hits"]}
        assert "1" in ids
        assert "2" in ids

    def test_radius_excludes_distant_document(self, backend, geo_docs):
        # 300 km radius from Madrid should exclude Barcelona (~505 km).
        result = backend.search("places", "", geo_point=(40.4168, -3.7038), geo_radius=300_000)
        ids = {h["id"] for h in result["hits"]}
        assert "3" not in ids

    def test_radius_excludes_documents_without_geo_field(self, backend, geo_docs):
        # Documents with no ``_geo`` field are always excluded when geo_radius is used.
        result = backend.search("places", "", geo_point=(40.4168, -3.7038), geo_radius=300_000)
        ids = {h["id"] for h in result["hits"]}
        assert "4" not in ids

    def test_very_small_radius_returns_only_origin(self, backend, geo_docs):
        # 1 km radius should return only Madrid itself.
        result = backend.search("places", "", geo_point=(40.4168, -3.7038), geo_radius=1_000)
        assert len(result["hits"]) == 1
        assert result["hits"][0]["id"] == "1"

    def test_large_radius_returns_all_geo_documents(self, backend, geo_docs):
        # 1000 km radius from Madrid covers all three geo docs.
        result = backend.search("places", "", geo_point=(40.4168, -3.7038), geo_radius=1_000_000)
        ids = {h["id"] for h in result["hits"]}
        assert {"1", "2", "3"} == ids

    def test_no_geo_field_on_any_document_returns_empty(self, backend):
        backend.add_documents("places", [{"id": "x", "name": "No location"}])
        result = backend.search("places", "", geo_point=(40.4168, -3.7038), geo_radius=1_000_000)
        assert result["hits"] == []


# ---------------------------------------------------------------------------
# DummyBackend — geo distance sorting
# ---------------------------------------------------------------------------


class TestDummyBackendGeoSort:
    """DummyBackend sorts documents by distance from geo_point."""

    def test_geo_sort_asc_orders_nearest_first(self, backend, geo_docs):
        result = backend.search("places", "", geo_point=(40.4168, -3.7038), geo_sort="asc")
        # Madrid is nearest, then Salamanca, then Barcelona.
        ids = [h["id"] for h in result["hits"] if "_geoDistance" in h]
        assert ids[0] == "1"
        assert ids[1] == "2"
        assert ids[2] == "3"

    def test_geo_sort_desc_orders_farthest_first(self, backend, geo_docs):
        result = backend.search("places", "", geo_point=(40.4168, -3.7038), geo_sort="desc")
        ids = [h["id"] for h in result["hits"] if "_geoDistance" in h]
        # Barcelona is furthest, so appears first in desc order.
        assert ids[0] == "3"
        assert ids[-1] == "1"

    def test_geo_sort_without_radius_includes_no_geo_document(self, backend, geo_docs):
        # Without a radius filter, doc "4" (no _geo) is still returned — it
        # just sorts to the end because _geoDistance defaults to infinity.
        result = backend.search("places", "", geo_point=(40.4168, -3.7038), geo_sort="asc")
        ids = [h["id"] for h in result["hits"]]
        assert "4" in ids
        # "4" should appear after all geo-annotated documents.
        assert ids.index("4") > ids.index("1")


# ---------------------------------------------------------------------------
# DummyBackend — _geoDistance annotation
# ---------------------------------------------------------------------------


class TestDummyBackendGeoDistance:
    """_geoDistance is added to hits when geo_point is provided."""

    def test_geo_distance_present_on_hits_with_geo_field(self, backend, geo_docs):
        result = backend.search("places", "", geo_point=(40.4168, -3.7038))
        geo_hits = [h for h in result["hits"] if "_geoDistance" in h]
        assert len(geo_hits) == 3  # docs 1, 2, 3 have _geo

    def test_geo_distance_is_integer_metres(self, backend, geo_docs):
        result = backend.search("places", "", geo_point=(40.4168, -3.7038))
        for hit in result["hits"]:
            if "_geoDistance" in hit:
                assert isinstance(hit["_geoDistance"], int)

    def test_geo_distance_zero_at_origin(self, backend, geo_docs):
        # doc "1" is at the origin point — its distance should be ~0.
        result = backend.search("places", "", geo_point=(40.4168, -3.7038))
        madrid_hit = next(h for h in result["hits"] if h["id"] == "1")
        assert madrid_hit["_geoDistance"] == pytest.approx(0, abs=10)

    def test_geo_distance_not_present_without_geo_point(self, backend, geo_docs):
        result = backend.search("places", "")
        for hit in result["hits"]:
            assert "_geoDistance" not in hit

    def test_geo_distance_not_present_on_hit_without_geo_field(self, backend, geo_docs):
        result = backend.search("places", "", geo_point=(40.4168, -3.7038))
        no_geo_hit = next(h for h in result["hits"] if h["id"] == "4")
        assert "_geoDistance" not in no_geo_hit

    def test_geo_distance_passes_through_from_engine(self):
        """SearchResult.from_engine preserves _geoDistance on hits."""
        raw = {
            "hits": [
                {"id": "1", "name": "Madrid", "_geoDistance": 0},
                {"id": "2", "name": "Barcelona", "_geoDistance": 505432},
            ],
            "query": "",
            "processingTimeMs": 0,
            "estimatedTotalHits": 2,
        }
        result = SearchResult.from_engine(raw)
        assert result.hits[0]["_geoDistance"] == 0
        assert result.hits[1]["_geoDistance"] == 505432

    def test_formatted_and_ranking_score_stripped_but_geo_distance_kept(self):
        """Only _formatted and _rankingScore are stripped, not _geoDistance."""
        raw = {
            "hits": [
                {
                    "id": "1",
                    "name": "Madrid",
                    "_geoDistance": 123,
                    "_rankingScore": 0.95,
                    "_formatted": {"name": "<mark>Madrid</mark>"},
                },
            ],
            "query": "madrid",
            "processingTimeMs": 1,
            "estimatedTotalHits": 1,
        }
        result = SearchResult.from_engine(raw)
        hit = result.hits[0]
        assert "_geoDistance" in hit
        assert "_rankingScore" not in hit
        assert "_formatted" not in hit


# ---------------------------------------------------------------------------
# DummyBackend — geo radius combined with text query
# ---------------------------------------------------------------------------


class TestDummyBackendGeoWithTextQuery:
    """Geo parameters work alongside text query filtering."""

    def test_geo_radius_combined_with_text_query(self, backend, geo_docs):
        # Only "Madrid" matches text "Madrid" and is within 1 km.
        result = backend.search(
            "places",
            "Madrid",
            geo_point=(40.4168, -3.7038),
            geo_radius=1_000,
        )
        assert len(result["hits"]) == 1
        assert result["hits"][0]["id"] == "1"

    def test_geo_radius_excludes_text_match_outside_radius(self, backend, geo_docs):
        # "Barcelona" matches text but is outside 300 km radius from Madrid.
        result = backend.search(
            "places",
            "Barcelona",
            geo_point=(40.4168, -3.7038),
            geo_radius=300_000,
        )
        assert result["hits"] == []


# ---------------------------------------------------------------------------
# Meilisearch backend — geo expression construction
# ---------------------------------------------------------------------------


class TestMeilisearchGeoFilter:
    """MeilisearchBackend injects _geoRadius into the search body."""

    def _make_backend(self) -> MeilisearchBackend:
        mock_client = MagicMock()
        mock_client.request.return_value = MagicMock(
            status_code=200,
            json=lambda: {"hits": [], "query": "", "processingTimeMs": 0, "estimatedTotalHits": 0},
        )
        backend = MeilisearchBackend.__new__(MeilisearchBackend)
        backend.url = "http://localhost:7700"
        backend.api_key = ""
        backend.timeout = 5
        backend._client = mock_client
        return backend

    def test_geo_radius_appended_to_filter_string(self):
        backend = self._make_backend()
        with patch.object(backend, "_request") as mock_req:
            mock_req.return_value = {"hits": [], "query": "", "processingTimeMs": 0, "estimatedTotalHits": 0}
            backend.search(
                "places",
                "",
                geo_point=(40.4168, -3.7038),
                geo_radius=5000,
            )
        body = mock_req.call_args[1]["json"]
        assert "_geoRadius(40.4168, -3.7038, 5000)" in body["filter"]

    def test_geo_radius_combined_with_existing_filter(self):
        backend = self._make_backend()
        with patch.object(backend, "_request") as mock_req:
            mock_req.return_value = {"hits": [], "query": "", "processingTimeMs": 0, "estimatedTotalHits": 0}
            backend.search(
                "places",
                "",
                filter={"is_active": True},
                geo_point=(40.4168, -3.7038),
                geo_radius=5000,
            )
        body = mock_req.call_args[1]["json"]
        assert "is_active = true" in body["filter"]
        assert "_geoRadius(40.4168, -3.7038, 5000)" in body["filter"]
        assert " AND " in body["filter"]

    def test_geo_sort_asc_prepended_to_sort_list(self):
        backend = self._make_backend()
        with patch.object(backend, "_request") as mock_req:
            mock_req.return_value = {"hits": [], "query": "", "processingTimeMs": 0, "estimatedTotalHits": 0}
            backend.search(
                "places",
                "",
                geo_point=(40.4168, -3.7038),
                geo_sort="asc",
            )
        body = mock_req.call_args[1]["json"]
        assert body["sort"][0] == "_geoPoint(40.4168, -3.7038):asc"

    def test_geo_sort_desc_prepended_to_sort_list(self):
        backend = self._make_backend()
        with patch.object(backend, "_request") as mock_req:
            mock_req.return_value = {"hits": [], "query": "", "processingTimeMs": 0, "estimatedTotalHits": 0}
            backend.search(
                "places",
                "",
                geo_point=(40.4168, -3.7038),
                geo_sort="desc",
            )
        body = mock_req.call_args[1]["json"]
        assert body["sort"][0] == "_geoPoint(40.4168, -3.7038):desc"

    def test_geo_sort_prepended_before_existing_sort_fields(self):
        backend = self._make_backend()
        with patch.object(backend, "_request") as mock_req:
            mock_req.return_value = {"hits": [], "query": "", "processingTimeMs": 0, "estimatedTotalHits": 0}
            backend.search(
                "places",
                "",
                sort=["-name"],
                geo_point=(40.4168, -3.7038),
                geo_sort="asc",
            )
        body = mock_req.call_args[1]["json"]
        assert body["sort"][0] == "_geoPoint(40.4168, -3.7038):asc"
        assert body["sort"][1] == "name:desc"

    def test_geo_params_not_forwarded_to_meilisearch_body(self):
        backend = self._make_backend()
        with patch.object(backend, "_request") as mock_req:
            mock_req.return_value = {"hits": [], "query": "", "processingTimeMs": 0, "estimatedTotalHits": 0}
            backend.search(
                "places",
                "",
                geo_point=(40.4168, -3.7038),
                geo_radius=5000,
                geo_sort="asc",
            )
        body = mock_req.call_args[1]["json"]
        assert "geo_point" not in body
        assert "geo_radius" not in body
        assert "geo_sort" not in body

    def test_geo_filter_not_added_when_only_geo_point_given(self):
        """geo_radius is required to add a geo filter."""
        backend = self._make_backend()
        with patch.object(backend, "_request") as mock_req:
            mock_req.return_value = {"hits": [], "query": "", "processingTimeMs": 0, "estimatedTotalHits": 0}
            backend.search(
                "places",
                "",
                geo_point=(40.4168, -3.7038),
            )
        body = mock_req.call_args[1]["json"]
        assert "filter" not in body

    def test_geo_sort_not_added_when_only_geo_point_given(self):
        """geo_sort is required to add a sort expression."""
        backend = self._make_backend()
        with patch.object(backend, "_request") as mock_req:
            mock_req.return_value = {"hits": [], "query": "", "processingTimeMs": 0, "estimatedTotalHits": 0}
            backend.search(
                "places",
                "",
                geo_point=(40.4168, -3.7038),
            )
        body = mock_req.call_args[1]["json"]
        assert "sort" not in body


# ---------------------------------------------------------------------------
# SearchableMixin — geo field generation
# ---------------------------------------------------------------------------


class TestSearchableMixinGeoField:
    """SearchableMixin produces _geo in the search document."""

    @pytest.mark.django_db
    def test_lat_lng_fields_produce_geo_document(self):
        from search_testapp.models import GeoVenue

        venue = GeoVenue.objects.create(name="Estadio Bernabéu", latitude=40.4530, longitude=-3.6883)
        doc = venue.to_search_document()
        assert "_geo" in doc
        assert doc["_geo"] == {"lat": 40.4530, "lng": -3.6883}

    @pytest.mark.django_db
    def test_geo_property_produces_geo_document(self):
        from search_testapp.models import GeoVenueWithProperty

        venue = GeoVenueWithProperty.objects.create(name="Camp Nou", lat=41.3809, lng=2.1228)
        doc = venue.to_search_document()
        assert "_geo" in doc
        assert doc["_geo"] == {"lat": 41.3809, "lng": 2.1228}

    @pytest.mark.django_db
    def test_no_geo_field_config_omits_geo_from_document(self):
        from search_testapp.models import Article

        article = Article.objects.create(title="No geo", body="test")
        doc = article.to_search_document()
        assert "_geo" not in doc

    def test_search_geo_field_class_attribute_defaults_to_empty_string(self):
        from icv_search.mixins import SearchableMixin

        assert SearchableMixin.search_geo_field == ""

    def test_search_lat_field_class_attribute_defaults_to_empty_string(self):
        from icv_search.mixins import SearchableMixin

        assert SearchableMixin.search_lat_field == ""

    def test_search_lng_field_class_attribute_defaults_to_empty_string(self):
        from icv_search.mixins import SearchableMixin

        assert SearchableMixin.search_lng_field == ""

    @pytest.mark.django_db
    def test_lat_lng_fields_take_precedence_over_geo_field(self):
        """When both search_lat_field/search_lng_field and search_geo_field
        are set, the explicit lat/lng fields are used."""
        from search_testapp.models import GeoVenue

        # GeoVenue uses search_lat_field + search_lng_field.
        venue = GeoVenue.objects.create(name="Test", latitude=1.0, longitude=2.0)
        doc = venue.to_search_document()
        assert doc["_geo"] == {"lat": 1.0, "lng": 2.0}

    @pytest.mark.django_db
    def test_geo_document_floats_are_cast(self):
        """Integer lat/lng values are cast to float in the _geo dict."""
        from search_testapp.models import GeoVenue

        venue = GeoVenue.objects.create(name="Cast test", latitude=40, longitude=-3)
        doc = venue.to_search_document()
        assert isinstance(doc["_geo"]["lat"], float)
        assert isinstance(doc["_geo"]["lng"], float)
