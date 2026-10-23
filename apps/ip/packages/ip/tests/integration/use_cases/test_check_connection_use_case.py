"""Narrow integration tests for CheckConnectionUseCase using local HTTP server."""

from __future__ import annotations

import pytest
from ip.engine.adapters.outbound.connectors.generic_http_connector import GenericHttpConnector
from ip.engine.application.use_cases.connections.check_connection_use_case import (
    CheckConnectionCommand,
    CheckConnectionUseCase,
)
from pytest_httpserver import HTTPServer

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_check_connection_use_case(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/api/v1/health",
        method="GET",
        headers={"X-API-Key": "valid_token"},
    ).respond_with_json({"status": "ok", "system": "Itron Head-End"})

    connector = GenericHttpConnector(allow_private_ips=True)
    use_case = CheckConnectionUseCase(connectors={connector.app_id: connector})

    cmd = CheckConnectionCommand(
        app_id="http",
        auth_type="API_KEY",
        public_config={
            "base_url": httpserver.url_for(""),
            "check_path": "/api/v1/health",
        },
        raw_credentials={"api_key": "valid_token"},
    )

    result = await use_case.execute(cmd)
    assert result.success is True
    assert result.status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_check_connection_unknown_connector_returns_structured_failure() -> None:
    use_case = CheckConnectionUseCase(connectors={})
    cmd = CheckConnectionCommand(
        app_id="non_existent_app",
        auth_type="API_KEY",
        public_config={},
        raw_credentials={},
    )
    result = await use_case.execute(cmd)
    assert result.success is False
    assert result.status == "FAILED"
    assert result.error_code == "CONNECTOR_NOT_FOUND"
    assert "non_existent_app" in str(result.message)
