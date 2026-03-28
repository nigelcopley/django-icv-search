"""Test URL conf for icv-search.

Wraps ``icv_search.urls`` without a namespace so that tests using
``ROOT_URLCONF`` can resolve patterns without the ``icv_search:`` prefix.

Usage in tests::

    @override_settings(ROOT_URLCONF="icv_search.testing.urls")
    def test_something(self, client):
        response = client.get("/health/")
"""

from django.urls import include, path

urlpatterns = [
    path("", include("icv_search.urls")),
]
