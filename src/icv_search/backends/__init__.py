"""Search backend loading and access."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.module_loading import import_string

if TYPE_CHECKING:
    from icv_search.backends.base import BaseSearchBackend

_backend_instance: BaseSearchBackend | None = None


def get_search_backend(*, force_new: bool = False) -> BaseSearchBackend:
    """Return the configured search backend instance.

    The backend is instantiated once per process and cached. Pass
    ``force_new=True`` to create a fresh instance (useful in tests).
    """
    global _backend_instance  # noqa: PLW0603

    if _backend_instance is not None and not force_new:
        return _backend_instance

    from icv_search.conf import (
        ICV_SEARCH_API_KEY,
        ICV_SEARCH_BACKEND,
        ICV_SEARCH_BACKEND_OPTIONS,
        ICV_SEARCH_TIMEOUT,
        ICV_SEARCH_URL,
    )

    backend_class = import_string(ICV_SEARCH_BACKEND)
    _backend_instance = backend_class(
        url=ICV_SEARCH_URL,
        api_key=ICV_SEARCH_API_KEY,
        timeout=ICV_SEARCH_TIMEOUT,
        **ICV_SEARCH_BACKEND_OPTIONS,
    )
    return _backend_instance


def reset_search_backend() -> None:
    """Clear the cached backend instance. Useful in tests."""
    global _backend_instance  # noqa: PLW0603
    _backend_instance = None
