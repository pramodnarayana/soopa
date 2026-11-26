from collections.abc import Callable
from typing import cast

import pytest
from edi.application.use_cases.process_inbound_as2_message_use_case import (
    ProcessInboundAs2Command,
    ProcessInboundAs2Result,
)
from edi.domain.exceptions import (
    As2InboundError,
    As2MdnDispositionModifier,
    OrchestrationError,
    RouteNotActiveEdiError,
)
from edi.domain.partner.as2.messages import AS2MDN
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from observability import NoOpLogger, NoOpMetrics, NoOpTracer, ObservabilityProvider
from secret_store.ports.secret_store_port import SecretStorePort
from seedwork.domain.exceptions import Result
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from as2_server.adapters.inbound.http.multipart import render_mdn_report
from as2_server.adapters.inbound.http.routers import as2, ops
from as2_server.dependencies import get_receive_as2_use_case
from as2_server.ports.outbound.repository_port import PartnerEntity

_InboundHandler = Callable[
    [ProcessInboundAs2Command], Result[ProcessInboundAs2Result, As2InboundError]
]


class _StubInboundAs2UseCase:
    def __init__(self, handler: _InboundHandler) -> None:
        self._handler = handler

    async def process_inbound_message(
        self, command: ProcessInboundAs2Command
    ) -> Result[ProcessInboundAs2Result, As2InboundError]:
        return self._handler(command)


class _RecordingLogger(NoOpLogger):
    def __init__(self) -> None:
        self.error_calls: list[tuple[str, dict[str, object]]] = []

    def error(self, event: str, **kwargs: object) -> None:
        self.error_calls.append((event, dict(kwargs)))


def _build_test_app(
    handler: _InboundHandler,
    *,
    logger: NoOpLogger | None = None,
) -> FastAPI:
    ObservabilityProvider.configure(
        tracer=NoOpTracer(),
        metrics=NoOpMetrics(),
        logger=logger or NoOpLogger(),
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
    ("inbound_error", "expected_modifier", "expected_text_fragment"),
    [
        (
            As2InboundError.decryption_failed(
                reason="bad key",
                as2_from="PARTNER_STATION",
                as2_to="SOOPA_STATION",
                message_id="<msg-001@partner.example>",
            ),
            As2MdnDispositionModifier.DECRYPTION_FAILED.value,
            "Failed to decrypt S/MIME payload.",
        ),
        (
            As2InboundError.authentication_failed(
                reason="bad signature",
                as2_from="PARTNER_STATION",
                as2_to="SOOPA_STATION",
                message_id="<msg-001@partner.example>",
            ),
            As2MdnDispositionModifier.AUTHENTICATION_FAILED.value,
            "Signature authentication failed.",
        ),
        (
            As2InboundError.integrity_failed(
                reason="mic mismatch",
                as2_from="PARTNER_STATION",
                as2_to="SOOPA_STATION",
                message_id="<msg-001@partner.example>",
            ),
            As2MdnDispositionModifier.INTEGRITY_CHECK_FAILED.value,
            "Message integrity check failed.",
        ),
        (
            As2InboundError.partnership_not_found(
                as2_from="PARTNER_STATION",
                as2_to="SOOPA_STATION",
                message_id="<msg-001@partner.example>",
            ),
            As2MdnDispositionModifier.INSUFFICIENT_MESSAGE_SECURITY.value,
            "PARTNER_STATION",
        ),
        (
            As2InboundError.tenant_not_found(
                isa_sender="LOGIFLOW",
                isa_receiver="GLTP",
                as2_from="PARTNER_STATION",
                as2_to="SOOPA_STATION",
                message_id="<msg-001@partner.example>",
            ),
            As2MdnDispositionModifier.UNEXPECTED_PROCESSING_ERROR.value,
            "ISA pair 'LOGIFLOW' -> 'GLTP'",
        ),
    ],
)
def test_receive_as2_first_class_error_returns_rfc4130_mdn_disposition(
    inbound_error: As2InboundError,
    expected_modifier: str,
    expected_text_fragment: str,
) -> None:
    def _return_err(
        _cmd: ProcessInboundAs2Command,
    ) -> Result[ProcessInboundAs2Result, As2InboundError]:
        return Result.fail(inbound_error)

    recording_logger = _RecordingLogger()
    client = TestClient(_build_test_app(_return_err, logger=recording_logger))
    response = client.post(
        "/as2/inbox",
        content=b"ISA*00*...",
        headers={
            "AS2-To": "SOOPA_STATION",
            "AS2-From": "PARTNER_STATION",
            "Message-ID": "<msg-001@partner.example>",
            "Content-Type": "application/pkcs7-mime; smime-type=enveloped-data",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("multipart/report")
    assert "message/disposition-notification" in response.text
    assert expected_modifier in response.text
    assert expected_text_fragment in response.text
    assert len(recording_logger.error_calls) == 1
    logged_event, logged_fields = recording_logger.error_calls[0]
    assert logged_event == "as2_inbound_rejected"
    assert logged_fields["error_code"] == inbound_error.code.value
    if "isa_sender" in inbound_error.details:
        assert logged_fields["isa_sender"] == inbound_error.details["isa_sender"]
        assert logged_fields["isa_receiver"] == inbound_error.details["isa_receiver"]


def test_receive_as2_inactive_route_returns_processed_mdn_to_remote_tp() -> None:
    routing_error = RouteNotActiveEdiError.for_isa_pair(
        isa_sender="LOGIFLOW",
        isa_receiver="GLTP",
        inactive_route_ids=("edi_inb_rt_123",),
        inactive_route_names=("Logiflow To Greatlakes",),
        as2_from="PARTNER_STATION",
        as2_to="SOOPA_STATION",
        message_id="<msg-003@partner.example>",
    )

    def _return_ok_with_routing_error(
        _cmd: ProcessInboundAs2Command,
    ) -> Result[ProcessInboundAs2Result, As2InboundError]:
        return Result.ok(
            ProcessInboundAs2Result(
                mdn_body=b"Disposition: automatic-action/MDN-sent-automatically; processed",
                mdn_headers={"Content-Type": "multipart/report"},
                edi_message_id="edi_msg_1",
                tenant_id="iam_ten_1",
                isa_sender="LOGIFLOW",
                isa_receiver="GLTP",
                routing_error=routing_error,
            )
        )

    recording_logger = _RecordingLogger()
    client = TestClient(_build_test_app(_return_ok_with_routing_error, logger=recording_logger))
    response = client.post(
        "/as2/inbox",
        content=b"ISA*00*...",
        headers={
            "AS2-To": "SOOPA_STATION",
            "AS2-From": "PARTNER_STATION",
            "Message-ID": "<msg-003@partner.example>",
        },
    )
    assert response.status_code == 200
    assert "processed" in response.text
    assert "error:" not in response.text
    assert len(recording_logger.error_calls) == 1
    logged_event, logged_fields = recording_logger.error_calls[0]
    assert logged_event == "as2_inbound_received_with_routing_error"
    assert logged_fields["error_code"] == "ROUTE_NOT_ACTIVE"
    assert logged_fields["isa_sender"] == "LOGIFLOW"
    assert logged_fields["isa_receiver"] == "GLTP"
    assert "Route Not Active" in str(logged_fields["error"])


def test_receive_as2_error_without_as2_headers_returns_400() -> None:
    def _return_err(
        _cmd: ProcessInboundAs2Command,
    ) -> Result[ProcessInboundAs2Result, As2InboundError]:
        return Result.fail(As2InboundError.parse_failed(reason="Missing required AS2 headers"))

    client = TestClient(_build_test_app(_return_err))
    response = client.post("/as2/inbox", content=b"invalid")
    assert response.status_code == 400
    assert "Missing required AS2 headers" in response.json()["detail"]


def test_receive_as2_orchestration_error_with_headers_returns_error_mdn() -> None:
    def _raise_orchestration(
        _cmd: ProcessInboundAs2Command,
    ) -> Result[ProcessInboundAs2Result, As2InboundError]:
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
    def _raise_orchestration(
        _cmd: ProcessInboundAs2Command,
    ) -> Result[ProcessInboundAs2Result, As2InboundError]:
        raise OrchestrationError("Downstream storage unavailable")

    client = TestClient(_build_test_app(_raise_orchestration))
    response = client.post("/as2/inbox", content=b"ISA*00*...")
    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"


def test_ops_health_ready_and_metrics_endpoints() -> None:
    test_app = _build_test_app(
        lambda _cmd: Result.ok(
            ProcessInboundAs2Result(
                mdn_body=b"ok",
                mdn_headers={"Content-Type": "text/plain"},
                edi_message_id="edi_msg_1",
                tenant_id="ten_1",
                isa_sender="LOGIFLOW",
                isa_receiver="GLTP",
            )
        )
    )
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
