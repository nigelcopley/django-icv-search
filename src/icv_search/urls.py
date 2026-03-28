"""URL patterns for icv-search.

Include in your project's urlconf::

    urlpatterns = [
        path("search/", include("icv_search.urls")),
    ]
"""

from django.urls import path

from icv_search.views import icv_search_click, icv_search_health

app_name = "icv_search"

urlpatterns = [
    path("health/", icv_search_health, name="health"),
    path("click/", icv_search_click, name="click"),
]
