"""Unit tests verifying standalone `config-watch-gateway` settings and ASGI bootstrap."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from identity.domain.identity_context import PLATFORM_TENANT_ID

from unified_api.bootstrap.config_sync import (
    PLATFORM_SHARED_CONFIG_TENANT_IDS,
    WatchGatewaySettings,
    create_watch_gateway_app,
)


async def test_watch_gateway_boots_without_web_cors_or_identity_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves ECS Fargate `config-watch-gateway` boots cleanly with minimal DB + token env vars."""
    expected_token = "staging-watch-tok"  # noqa: S105 - Synthetic bearer token for unit test only
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("IDENTITY_ISSUER", raising=False)
    monkeypatch.setenv("ENV", "staging")
    monkeypatch.setenv("ENABLED_APPS", "edi")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/global_db")
    monkeypatch.setenv("CONFIG_SYNC_INTERNAL_TOKEN", expected_token)

    settings = WatchGatewaySettings()
    assert settings.env == "staging"
    assert settings.enabled_apps == "edi"
    assert settings.config_sync_internal_token == expected_token
    assert PLATFORM_SHARED_CONFIG_TENANT_IDS == (PLATFORM_TENANT_ID,)

    app = create_watch_gateway_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://watch-gateway.internal",
    ) as client:
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json() == {"status": "ok", "service": "config-watch-gateway"}

        # Verify fail-closed Bearer authentication works on `/api/v1/internal/edi/config/snapshot`
        unauth_resp = await client.get(
            "/api/v1/internal/edi/config/snapshot",
            params={"tenant_id": "ten_1"},
        )
        assert unauth_resp.status_code == 401


def test_unified_api_main_does_not_dual_mount_config_sync_router() -> None:
    """Enforces zero dual-mount split-brain: watch_gateway.py is the sole owner of config-sync routes."""
    main_path = Path(__file__).resolve().parents[2] / "src" / "unified_api" / "main.py"
    source = main_path.read_text(encoding="utf-8")
    assert "create_config_sync_router" not in source
    assert "build_config_watch_stream_use_case" not in source
