"""Tests for ICVSearchTenantMiddleware and get_current_tenant_id()."""

from __future__ import annotations

import pytest
from django.test import RequestFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tenant_func(tenant_id: str):
    """Return a callable that always returns *tenant_id*."""

    def get_tenant(request):
        return tenant_id

    return get_tenant


def _get_response(request):
    """Minimal Django get_response stand-in."""
    from django.http import HttpResponse

    return HttpResponse("ok")


# ---------------------------------------------------------------------------
# Tests for get_current_tenant_id() outside of a request
# ---------------------------------------------------------------------------


class TestGetCurrentTenantIdOutsideRequest:
    """Behaviour of get_current_tenant_id() with no active middleware."""

    def test_returns_empty_string_by_default(self):
        from icv_search.middleware import get_current_tenant_id

        assert get_current_tenant_id() == ""

    def test_returns_str_type(self):
        from icv_search.middleware import get_current_tenant_id

        result = get_current_tenant_id()
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Tests for ICVSearchTenantMiddleware
# ---------------------------------------------------------------------------


class TestICVSearchTenantMiddleware:
    """Middleware sets and clears the request-scoped tenant."""

    def test_no_op_when_setting_not_configured(self, settings):
        """Middleware is a no-op when ICV_SEARCH_TENANT_PREFIX_FUNC is empty."""
        settings.ICV_SEARCH_TENANT_PREFIX_FUNC = ""

        from icv_search.middleware import ICVSearchTenantMiddleware, get_current_tenant_id

        seen = []

        def capturing_get_response(request):
            seen.append(get_current_tenant_id())
            return _get_response(request)

        middleware = ICVSearchTenantMiddleware(capturing_get_response)
        request = RequestFactory().get("/")
        middleware(request)

        assert seen == [""]

    def test_extracts_tenant_from_prefix_func(self, settings):
        """Middleware calls TENANT_PREFIX_FUNC and stores the return value."""
        settings.ICV_SEARCH_TENANT_PREFIX_FUNC = "tests.test_middleware._make_tenant_func"

        # Override to inject a simple callable directly to avoid import gymnastics
        import icv_search.middleware as mw

        original_get = mw.ICVSearchTenantMiddleware._get_prefix_func

        def patched_get(self):
            return lambda req: "acme"

        mw.ICVSearchTenantMiddleware._get_prefix_func = patched_get

        try:
            from icv_search.middleware import ICVSearchTenantMiddleware, get_current_tenant_id

            seen = []

            def capturing_get_response(request):
                seen.append(get_current_tenant_id())
                return _get_response(request)

            middleware = ICVSearchTenantMiddleware(capturing_get_response)
            request = RequestFactory().get("/")
            middleware(request)

            assert seen == ["acme"]
        finally:
            mw.ICVSearchTenantMiddleware._get_prefix_func = original_get

    def test_clears_tenant_after_request(self, settings):
        """Tenant is cleared from thread-local storage after the response."""
        import icv_search.middleware as mw

        original_get = mw.ICVSearchTenantMiddleware._get_prefix_func

        def patched_get(self):
            return lambda req: "beta"

        mw.ICVSearchTenantMiddleware._get_prefix_func = patched_get

        try:
            from icv_search.middleware import ICVSearchTenantMiddleware, get_current_tenant_id

            middleware = ICVSearchTenantMiddleware(_get_response)
            request = RequestFactory().get("/")
            middleware(request)

            # After the call the thread-local must be empty
            assert get_current_tenant_id() == ""
        finally:
            mw.ICVSearchTenantMiddleware._get_prefix_func = original_get

    def test_clears_tenant_even_on_exception(self, settings):
        """Thread-local is cleared if get_response raises."""
        import icv_search.middleware as mw

        original_get = mw.ICVSearchTenantMiddleware._get_prefix_func

        def patched_get(self):
            return lambda req: "gamma"

        mw.ICVSearchTenantMiddleware._get_prefix_func = patched_get

        try:
            from icv_search.middleware import ICVSearchTenantMiddleware, get_current_tenant_id

            def raising_get_response(request):
                raise RuntimeError("boom")

            middleware = ICVSearchTenantMiddleware(raising_get_response)
            request = RequestFactory().get("/")
            with pytest.raises(RuntimeError):
                middleware(request)

            assert get_current_tenant_id() == ""
        finally:
            mw.ICVSearchTenantMiddleware._get_prefix_func = original_get

    def test_tenant_func_returning_none_yields_empty_string(self, settings):
        """A TENANT_PREFIX_FUNC returning None results in an empty tenant string."""
        import icv_search.middleware as mw

        original_get = mw.ICVSearchTenantMiddleware._get_prefix_func

        def patched_get(self):
            return lambda req: None

        mw.ICVSearchTenantMiddleware._get_prefix_func = patched_get

        try:
            from icv_search.middleware import ICVSearchTenantMiddleware, get_current_tenant_id

            seen = []

            def capturing_get_response(request):
                seen.append(get_current_tenant_id())
                return _get_response(request)

            middleware = ICVSearchTenantMiddleware(capturing_get_response)
            request = RequestFactory().get("/")
            middleware(request)

            assert seen == [""]
        finally:
            mw.ICVSearchTenantMiddleware._get_prefix_func = original_get

    def test_tenant_func_exception_yields_empty_string(self, settings):
        """A TENANT_PREFIX_FUNC that raises does not propagate; empty string is used."""
        import icv_search.middleware as mw

        original_get = mw.ICVSearchTenantMiddleware._get_prefix_func

        def patched_get(self):
            def bad_func(req):
                raise ValueError("misconfigured")

            return bad_func

        mw.ICVSearchTenantMiddleware._get_prefix_func = patched_get

        try:
            from icv_search.middleware import ICVSearchTenantMiddleware, get_current_tenant_id

            seen = []

            def capturing_get_response(request):
                seen.append(get_current_tenant_id())
                return _get_response(request)

            middleware = ICVSearchTenantMiddleware(capturing_get_response)
            request = RequestFactory().get("/")
            # Must not raise — middleware swallows prefix-func errors
            middleware(request)

            assert seen == [""]
        finally:
            mw.ICVSearchTenantMiddleware._get_prefix_func = original_get


# ---------------------------------------------------------------------------
# Tests for resolve_tenant_id() interaction with middleware
# ---------------------------------------------------------------------------


class TestResolveTenantId:
    """Explicit tenant_id always wins over middleware-provided value."""

    def test_explicit_tenant_id_takes_precedence(self, settings):
        """An explicit tenant_id is returned regardless of the middleware state."""
        from icv_search.middleware import _tenant_state
        from icv_search.services._utils import resolve_tenant_id

        _tenant_state.tenant_id = "middleware-tenant"
        try:
            result = resolve_tenant_id("explicit-tenant")
            assert result == "explicit-tenant"
        finally:
            _tenant_state.tenant_id = ""

    def test_falls_back_to_middleware_when_empty(self):
        """An empty explicit tenant_id falls back to the middleware value."""
        from icv_search.middleware import _tenant_state
        from icv_search.services._utils import resolve_tenant_id

        _tenant_state.tenant_id = "request-tenant"
        try:
            result = resolve_tenant_id("")
            assert result == "request-tenant"
        finally:
            _tenant_state.tenant_id = ""

    def test_returns_empty_when_both_absent(self):
        """Returns empty string when neither explicit nor middleware tenant is set."""
        from icv_search.services._utils import resolve_tenant_id

        result = resolve_tenant_id("")
        assert result == ""
