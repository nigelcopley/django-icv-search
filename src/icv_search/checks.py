"""Django system checks for icv_search."""

from django.core.checks import Error, Tags, register
from django.utils.module_loading import import_string


@register(Tags.models)
def check_icv_search_configuration(app_configs, **kwargs):
    """Validate icv_search configuration at Django startup."""
    from icv_search.conf import (
        ICV_SEARCH_BACKEND,
        ICV_SEARCH_TIMEOUT,
        ICV_SEARCH_URL,
    )

    errors = []

    # ICV_SEARCH_BACKEND: must be a valid import path
    if not ICV_SEARCH_BACKEND:
        errors.append(
            Error(
                "ICV_SEARCH_BACKEND is not set.",
                hint="Set ICV_SEARCH_BACKEND to a backend class path (e.g., 'icv_search.backends.meilisearch.MeilisearchBackend').",
                id="icv_search.E001",
            )
        )
    else:
        try:
            import_string(ICV_SEARCH_BACKEND)
        except ImportError as e:
            errors.append(
                Error(
                    f"ICV_SEARCH_BACKEND cannot be imported: {e}",
                    hint=f"Current value: {ICV_SEARCH_BACKEND!r}. Ensure the path is correct.",
                    id="icv_search.E002",
                )
            )

    # ICV_SEARCH_URL: validate format if using Meilisearch backend
    if "meilisearch" in ICV_SEARCH_BACKEND.lower() and (
        not ICV_SEARCH_URL or not ICV_SEARCH_URL.startswith(("http://", "https://"))
    ):
        errors.append(
            Error(
                "ICV_SEARCH_URL must be a valid HTTP/HTTPS URL when using Meilisearch backend.",
                hint=f"Current value: {ICV_SEARCH_URL!r}. Set to 'http://localhost:7700' or your Meilisearch URL.",
                id="icv_search.E003",
            )
        )

    # ICV_SEARCH_TIMEOUT: must be positive
    if not isinstance(ICV_SEARCH_TIMEOUT, int) or ICV_SEARCH_TIMEOUT <= 0:
        errors.append(
            Error(
                "ICV_SEARCH_TIMEOUT must be a positive integer.",
                hint=f"Current value: {ICV_SEARCH_TIMEOUT}. Set to timeout in seconds (e.g., 30).",
                id="icv_search.E004",
            )
        )

    return errors
