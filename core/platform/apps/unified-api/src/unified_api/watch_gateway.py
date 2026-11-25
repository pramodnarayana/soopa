"""Dedicated Shopify-style ASGI entrypoint for the Control Plane Config Watch Gateway.

Run with:
    uvicorn unified_api.watch_gateway:app --host 0.0.0.0 --port 8081
"""

from __future__ import annotations

from unified_api.bootstrap.config_sync import create_watch_gateway_app

app = create_watch_gateway_app()

__all__ = ["app"]
