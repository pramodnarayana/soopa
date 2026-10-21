"""Unit tests for ingress router header filtering and connection status validation."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import HTTPException
from identity.domain.identity_context import IdentityContext
from ip.domain.models.connection import AuthType, Connection
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from unified_api.adapters.inbound.http.ip.routers.ingress_router import (
    _is_allowed_ingress_header,
    ingest_record,
)


class FakeConnectionRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    async def get_by_id(self, connection_id: str) -> Connection | None:
        return self._connection


def test_is_allowed_ingress_header_blocks_sensitive_headers() -> None:
    # Must block sensitive credentials case-insensitively
    assert _is_allowed_ingress_header("Authorization") is False
    assert _is_allowed_ingress_header("authorization") is False
    assert _is_allowed_ingress_header("Cookie") is False
    assert _is_allowed_ingress_header("Set-Cookie") is False
    assert _is_allowed_ingress_header("X-API-KEY") is False
    assert _is_allowed_ingress_header("x-api-key") is False
    assert _is_allowed_ingress_header("Proxy-Authorization") is False


def test_is_allowed_ingress_header_allows_metadata_and_webhook_signatures() -> None:
    assert _is_allowed_ingress_header("Content-Type") is True
    assert _is_allowed_ingress_header("User-Agent") is True
    assert _is_allowed_ingress_header("X-Correlation-ID") is True
    assert _is_allowed_ingress_header("X-Request-ID") is True
    assert _is_allowed_ingress_header("X-Vendor") is True
    assert _is_allowed_ingress_header("stripe-signature") is True
    assert _is_allowed_ingress_header("x-hub-signature-256") is True


@pytest.mark.asyncio
async def test_ingest_record_raises_409_for_deactivated_connection() -> None:
    mock_conn = Connection.create(
        tenant_id="ten_1",
        app_id="itron_mdm",
        name="Deactivated Connection",
        auth_type=AuthType.API_KEY,
        public_config={},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://api.example.com",
    )
    mock_conn.deactivate()

    session = cast(AsyncSession, object())
    request = Request(scope={"type": "http", "headers": [(b"x-correlation-id", b"test-123")]})
    context = IdentityContext(subject="user_1", claims={}, tenant_id="ten_1")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "unified_api.adapters.inbound.http.ip.routers.ingress_router.SqlAlchemyConnectionRepository",
            lambda session: FakeConnectionRepository(mock_conn),
        )

        with pytest.raises(HTTPException) as exc_info:
            await ingest_record(
                tenant_id="ten_1",
                connection_id=mock_conn.id,
                request=request,
                context=context,
                session=session,
                stream_name="meters",
                body={"reading": 42},
                correlation_id="test-123",
            )

        assert exc_info.value.status_code == 409
        assert "is deactivated and cannot accept ingress" in exc_info.value.detail
