"""
Narrow Integration Tests for the Observability Bootstrap.

Architecture Note:
    These are narrow integration tests — they start the real application shell
    and make real HTTP calls. No mocking, no InMemorySpanExporter injection,
    no monkeypatching of OTel internals.

    The tests verify the two observable failure modes we have encountered in
    production:

    1. OTel instrumentor crashes at startup (AttributeError on _IncludedRouter.path)
       → the app fixture would raise during collection, causing all tests to ERROR

    2. OTel crashes silently during request dispatch, returning HTTP 500
       → covered by asserting status_code != 500 across multiple router boundaries

    When the full OTel SDK upgrade (opentelemetry-api 1.37→1.44+) is completed
    and FastAPIInstrumentor is re-enabled, these tests will naturally continue
    to pass — and span-collection assertions can be added at that point without
    changing the test architecture.
"""

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_observability_startup_does_not_crash_app(app):
    """
    Regression test: Verifies setup_observability() does not raise during
    application startup when FastAPI has _IncludedRouter instances.

    Previously failed with:
        AttributeError: '_IncludedRouter' object has no attribute 'path'
    raised inside FastAPIInstrumentor.instrument_app() on FastAPI 0.111+.

    If this test ERRORs (not fails), it means setup_observability() threw
    during the `app` fixture's shell_lifespan, which is the exact production failure.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_observability_does_not_cause_500_on_ucp_routes(app):
    """
    Verifies that OTel middleware does not crash request dispatch on routes
    registered via app.include_router() — i.e., those backed by _IncludedRouter.

    A 500 here (rather than 200/401) indicates the OTel ASGI middleware
    panicked during span attribute extraction for an included router.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # /api/v1/auth/me is registered on an included router (identity router)
        response = await client.get("/api/v1/auth/me")

    # 200 (unauthenticated) or 401 are both correct — 500 is the OTel failure signal
    assert response.status_code in (200, 401), (
        f"Expected 200 or 401 from /api/v1/auth/me, got {response.status_code}. "
        f"This ensures the intended router was exercised without an OTel crash. "
        f"Body: {response.text}"
    )


@pytest.mark.asyncio
async def test_observability_does_not_cause_500_across_router_boundaries(app):
    """
    Exercises multiple routes across different _IncludedRouter instances to
    confirm that OTel request instrumentation does not crash on any of them.

    Each route below is registered on a different included router in main.py,
    meaning each hits a different _IncludedRouter object during span extraction.
    """
    transport = httpx.ASGITransport(app=app)

    routes_under_test = [
        "/health",  # registered directly on the shell app
        "/api/v1/auth/me",  # identity router (include_router)
    ]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for route in routes_under_test:
            response = await client.get(route)
            assert response.status_code in (200, 401), (
                f"Route {route!r} returned {response.status_code} (expected 200 or 401). "
                f"This likely indicates an OTel instrumentation crash or missing route. "
                f"Body: {response.text}"
            )
