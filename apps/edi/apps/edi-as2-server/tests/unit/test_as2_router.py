from collections.abc import Callable
from typing import cast

import pytest
from edi.application.use_cases.process_inbound_as2_message_use_case import (
    ProcessInboundAs2Command,
)
from edi.domain.exceptions import OrchestrationError
from edi.domain.partner.as2.messages import AS2MDN
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from observability import NoOpLogger, NoOpMetrics, NoOpTracer, ObservabilityProvider
from secret_store.ports.secret_store_port import SecretStorePort
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from as2_server.adapters.inbound.http.multipart import render_mdn_report
from as2_server.adapters.inbound.http.routers import as2, ops
from as2_server.dependencies import get_receive_as2_use_case
from as2_server.ports.outbound.repository_port import PartnerEntity


class _StubInboundAs2UseCase:
    def __init__(
        self,
        handler: Callable[[ProcessInboundAs2Command], tuple[bytes, dict[str, str]]],
    ) -> None:
        self._handler = handler

    async def process_inbound_message(
        self, command: ProcessInboundAs2Command
    ) -> tuple[bytes, dict[str, str]]:
        return self._handler(command)


def _build_test_app(
    handler: Callable[[ProcessInboundAs2Command], tuple[bytes, dict[str, str]]],
) -> FastAPI:
    ObservabilityProvider.configure(
        tracer=NoOpTracer(),
        metrics=NoOpMetrics(),
        logger=NoOpLogger(),
    )
    test_app = FastAPI()
    test_app.state.db_router = object()
    test_app.state.s3_storage = object()
    test_app.include_router(as2.router)
    test_app.include_router(ops.router)
    test_app.dependency_overrides[get_receive_as2_use_case] = lambda: _StubInboundAs2UseCase(
        handler
    )
    return test_app


@pytest.mark.parametrize(
    ("error_message", "expected_modifier"),
    [
        ("Failed to decrypt S/MIME payload", "error: decryption-failed"),
        ("Certificate signature verification failed", "error: authentication-failed"),
        ("Calculated MIC digest mismatch", "error: integrity-check-failed"),
        ("Active partnership security policy missing", "error: insufficient-message-security"),
        ("Unrecognized EDI interchange envelope", "error: unexpected-processing-error"),
    ],
)
def test_receive_as2_value_error_returns_rfc4130_mdn_disposition(
    error_message: str,
    expected_modifier: str,
) -> None:
    def _raise_value_error(_cmd: ProcessInboundAs2Command) -> tuple[bytes, dict[str, str]]:
        raise ValueError(error_message)

    client = TestClient(_build_test_app(_raise_value_error))
    response = client.post(
        "/as2/inbox",
        content=b"ISA*00*...",
        headers={
            "AS2-To": "SOOPA_STATION",
            "AS2-From": "PARTNER_STATION",
            "Message-ID": "<msg-001@partner.example>",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("multipart/report")
    assert "message/disposition-notification" in response.text
    assert expected_modifier in response.text


def test_receive_as2_value_error_without_as2_headers_returns_400() -> None:
    def _raise_value_error(_cmd: ProcessInboundAs2Command) -> tuple[bytes, dict[str, str]]:
        raise ValueError("Missing required AS2 envelope headers")

    client = TestClient(_build_test_app(_raise_value_error))
    response = client.post("/as2/inbox", content=b"invalid")
    assert response.status_code == 400
    assert "Missing required AS2 envelope headers" in response.json()["detail"]


def test_receive_as2_orchestration_error_with_headers_returns_error_mdn() -> None:
    def _raise_orchestration(_cmd: ProcessInboundAs2Command) -> tuple[bytes, dict[str, str]]:
        raise OrchestrationError("Downstream storage unavailable")

    client = TestClient(_build_test_app(_raise_orchestration))
    response = client.post(
        "/as2/inbox",
        content=b"ISA*00*...",
        headers={
            "AS2-To": "SOOPA_STATION",
            "AS2-From": "PARTNER_STATION",
            "Message-ID": "<msg-002@partner.example>",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("multipart/report")
    assert "message/disposition-notification" in response.text
    assert "error: unexpected-processing-error" in response.text


def test_receive_as2_orchestration_error_without_headers_returns_500() -> None:
    def _raise_orchestration(_cmd: ProcessInboundAs2Command) -> tuple[bytes, dict[str, str]]:
        raise OrchestrationError("Downstream storage unavailable")

    client = TestClient(_build_test_app(_raise_orchestration))
    response = client.post("/as2/inbox", content=b"ISA*00*...")
    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"


def test_ops_health_ready_and_metrics_endpoints() -> None:
    test_app = _build_test_app(lambda _cmd: (b"ok", {"Content-Type": "text/plain"}))
    client = TestClient(test_app)

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}
    metrics_res = client.get("/metrics")
    assert metrics_res.status_code == 200

    test_app.state.s3_storage = None
    assert client.get("/ready").status_code == 503

    test_app.state.db_router = None
    assert client.get("/ready").status_code == 503


def test_dependencies_guard_uninitialized_app_state() -> None:
    state_holder = FastAPI()
    state_holder.state.s3_storage = None
    state_holder.state.db_router = None
    state_holder.state.tenant_resolver = None
    state_holder.state.publisher = None
    state_holder.state.crypto_service = None

    scope = {"type": "http", "app": state_holder, "headers": [], "method": "POST", "path": "/"}
    req = Request(scope)
    dummy_session = cast(AsyncSession, object())
    dummy_vault = cast(SecretStorePort, object())

    with pytest.raises(HTTPException) as exc_s3:
        get_receive_as2_use_case(req, dummy_session, dummy_vault)
    assert exc_s3.value.status_code == 503

    state_holder.state.s3_storage = object()
    with pytest.raises(HTTPException) as exc_db:
        get_receive_as2_use_case(req, dummy_session, dummy_vault)
    assert exc_db.value.status_code == 503

    state_holder.state.db_router = object()
    with pytest.raises(HTTPException) as exc_tenant:
        get_receive_as2_use_case(req, dummy_session, dummy_vault)
    assert exc_tenant.value.status_code == 503

    state_holder.state.tenant_resolver = object()
    with pytest.raises(HTTPException) as exc_pub:
        get_receive_as2_use_case(req, dummy_session, dummy_vault)
    assert exc_pub.value.status_code == 503

    state_holder.state.publisher = object()
    with pytest.raises(HTTPException) as exc_crypto:
        get_receive_as2_use_case(req, dummy_session, dummy_vault)
    assert exc_crypto.value.status_code == 503


def test_render_mdn_report_and_partner_entity() -> None:
    partner = PartnerEntity(
        as2_id="STATION_A",
        public_cert_pem="-----BEGIN CERTIFICATE-----",
        active=True,
        private_key_vault_ref="vault://as2_keys/key1",
    )
    assert partner.as2_id == "STATION_A"
    assert partner.active is True

    processed_mdn = AS2MDN(
        original_message_id="msg-100",
        disposition="automatic-action/MDN-sent-automatically; processed",
        mic="abc123==, sha256",
    )
    rendered_ok = render_mdn_report(processed_mdn).decode("utf-8")
    assert "The AS2 message has been processed." in rendered_ok
    assert "Received-content-MIC: abc123==, sha256" in rendered_ok

    decrypt_err = AS2MDN(
        original_message_id="msg-101",
        disposition="automatic-action/MDN-sent-automatically; processed/error: decryption-failed",
    )
    assert b"failed decryption" in render_mdn_report(decrypt_err)

    auth_err = AS2MDN(
        original_message_id="msg-102",
        disposition="automatic-action/MDN-sent-automatically; processed/error: authentication-failed",
    )
    assert b"failed authentication" in render_mdn_report(auth_err)

    generic_err = AS2MDN(
        original_message_id="msg-103",
        disposition="automatic-action/MDN-sent-automatically; failed",
    )
    assert b"processing failed" in render_mdn_report(generic_err)
