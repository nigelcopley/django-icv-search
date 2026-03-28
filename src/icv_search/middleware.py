"""Middleware for icv-search."""

from __future__ import annotations

import threading

from django.http import HttpRequest, HttpResponse
from django.utils.module_loading import import_string

# Thread-local storage for the request-scoped tenant identifier.
# Follows the same pattern as ``_skip_state`` in ``auto_index.py``.
_tenant_state = threading.local()


def get_current_tenant_id() -> str:
    """Return the tenant identifier set by :class:`ICVSearchTenantMiddleware`.

    Returns an empty string when called outside of a request context (e.g.
    Celery tasks, management commands) or when
    :class:`ICVSearchTenantMiddleware` is not active in the middleware stack.
    """
    return getattr(_tenant_state, "tenant_id", "")


class ICVSearchTenantMiddleware:
    """Middleware that extracts the tenant context from the request and stores
    it in thread-local storage so search operations automatically scope to
    the correct tenant without requiring explicit ``tenant_id`` parameters.

    Configure ``ICV_SEARCH_TENANT_PREFIX_FUNC`` in your Django settings to a
    dotted-path callable that accepts ``(request)`` and returns a tenant
    identifier string.  When the setting is absent or empty, the middleware is
    a no-op and :func:`get_current_tenant_id` always returns an empty string.

    Add to your ``MIDDLEWARE`` setting after authentication middleware::

        MIDDLEWARE = [
            ...
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            "icv_search.middleware.ICVSearchTenantMiddleware",
            ...
        ]
    """

    def __init__(self, get_response) -> None:
        self.get_response = get_response
        self._prefix_func = None
        self._prefix_func_loaded = False

    def __call__(self, request: HttpRequest) -> HttpResponse:
        tenant_id = self._resolve_tenant_id(request)
        _tenant_state.tenant_id = tenant_id
        try:
            response = self.get_response(request)
        finally:
            # Always clear tenant from thread-local — ensures no cross-request leakage.
            _tenant_state.tenant_id = ""
        return response

    def _resolve_tenant_id(self, request: HttpRequest) -> str:
        """Invoke ``ICV_SEARCH_TENANT_PREFIX_FUNC`` and return the result.

        Returns an empty string when the setting is not configured or when
        the callable returns a falsy value.
        """
        func = self._get_prefix_func()
        if func is None:
            return ""
        try:
            result = func(request)
            return result or ""
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "ICV_SEARCH_TENANT_PREFIX_FUNC raised an exception — using empty tenant."
            )
            return ""

    def _get_prefix_func(self):
        """Lazily load and cache the tenant prefix callable.

        Reading the setting inside the method body (rather than in
        ``__init__``) ensures that pytest ``settings`` fixture overrides take
        effect, consistent with the rest of the package's ``conf.py`` pattern.
        """
        from django.conf import settings

        func_path: str = getattr(settings, "ICV_SEARCH_TENANT_PREFIX_FUNC", "")
        if not func_path:
            return None
        if not self._prefix_func_loaded or getattr(self._prefix_func, "_path", None) != func_path:
            self._prefix_func = import_string(func_path)
            self._prefix_func._path = func_path  # type: ignore[attr-defined]
            self._prefix_func_loaded = True
        return self._prefix_func
