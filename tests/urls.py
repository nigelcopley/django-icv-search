"""Test URL conf for icv-search.

Wraps ``icv_search.urls`` without a namespace so that tests using
``ROOT_URLCONF`` can resolve patterns without the ``icv_search:`` prefix.
"""

from django.urls import include, path

urlpatterns = [
    path("", include("icv_search.urls")),
]
