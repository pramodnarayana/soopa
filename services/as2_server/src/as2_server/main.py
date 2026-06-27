"""
Production-ready FastAPI application for the EDI AS2 Server.
"""

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from as2_core import (
    decrypt_payload,
    generate_mdn,
    parse_as2_request,
    render_mdn_report,
    verify_signature,
)
from config.settings import get_settings
from database.repository import (
    EdiMessageRepository,
    TradingPartnerRepository,
)
from database.s3 import Aioboto3PayloadStorage, IPayloadStorage
from database.session import get_session
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from identity.tenant_context import tenant_context
from observability import (
    ObservabilityProvider,
    OtelTracer,
    PrometheusMetrics,
    StructlogLogger,
)
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.ext.asyncio import AsyncSession

settings = get_settings()

# S3 Singleton
s3_storage: IPayloadStorage | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global s3_storage

    ObservabilityProvider.configure(
        tracer=OtelTracer(
            service_name=settings.otel.service_name,
            otlp_endpoint=settings.otel.exporter_otlp_endpoint,
        ),
        metrics=PrometheusMetrics(namespace="edi"),
        logger=StructlogLogger(name="edi", log_level=settings.log_level),
    )

    s3_storage = Aioboto3PayloadStorage(
        bucket=settings.s3.bucket,
        region=settings.s3.region,
        endpoint_url=settings.s3.endpoint_url,
        access_key_id=settings.s3.access_key_id,
        secret_access_key=settings.s3.secret_access_key,
    )

    logger = ObservabilityProvider.logger(__name__)
    from database.connection import DatabaseRouter

    try:
        # Initialize the global DatabaseRouter and mount it to app state
        db_router = DatabaseRouter(
            settings.database.global_url,
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
        )
        app.state.db_router = db_router
        print("LIFESPAN: DB Router initialized")
    except Exception as e:
        print(f"LIFESPAN DB ROUTER ERROR: {e}")

    logger.info("edi_as2_server_started", env=settings.env)
    yield
    logger.info("edi_as2_server_stopped")
    await db_router.close_all()


app = FastAPI(title="AS2 Server", version="1.0.0", lifespan=lifespan)
SessionDep = Annotated[AsyncSession, Depends(get_session)]


# Provide S3 as a FastAPI dependency for easy mocking in tests
def get_s3_storage() -> IPayloadStorage:
    if s3_storage is None:
        raise RuntimeError("S3 Storage not initialized")
    return s3_storage


def get_host_private_key() -> bytes:
    """
    Load the host AS2 private key PEM from an environment variable or mounted secret.
    In production, this should be sourced from a secure vault (e.g. HashiCorp Vault / AWS Secrets Manager).
    """
    import os

    key_pem = os.getenv("AS2_HOST_PRIVATE_KEY_PEM", "")
    return key_pem.encode("utf-8") if key_pem else b""


def get_host_certificate() -> bytes:
    """
    Load the host AS2 public certificate PEM from an environment variable or mounted secret.
    """
    import os

    cert_pem = os.getenv("AS2_HOST_PUBLIC_CERT_PEM", "")
    return cert_pem.encode("utf-8") if cert_pem else b""


S3Dep = Annotated[IPayloadStorage, Depends(get_s3_storage)]


@app.get("/health", tags=["ops"])
async def health() -> Any:
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
async def ready(request: Request, s3: S3Dep) -> Any:
    if getattr(request.app.state, "db_router", None) is None:
        raise HTTPException(status_code=503, detail="Database router not initialized")
    return {"status": "ready"}


@app.get("/metrics", tags=["ops"])
async def metrics() -> Any:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/as2", tags=["as2"])
async def receive_as2(request: Request, session: SessionDep, s3: S3Dep) -> Any:
    tracer = ObservabilityProvider.tracer()
    metrics = ObservabilityProvider.metrics()
    logger = ObservabilityProvider.logger(__name__)

    start_time = time.perf_counter()
    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    # --- Step 1: Parse ---
    with tracer.start_span("as2.parse") as span:
        try:
            as2_msg = parse_as2_request(headers, raw_body)
            span.set_attribute("as2.message_id", as2_msg.message_id)
        except ValueError as e:
            logger.warning("as2_parse_failed", error=str(e))
            raise HTTPException(status_code=400, detail=str(e)) from e

    # Resolve tenant_id from AS2-To header by looking up in global trading_partners table
    from database.models.control_plane import TradingPartner as GlobalTradingPartner
    from sqlalchemy import select as sql_select

    tenant_id = 1  # Default fallback
    try:
        result = await session.execute(
            sql_select(GlobalTradingPartner.tenant_id)
            .where(GlobalTradingPartner.as2_id == as2_msg.as2_to)
            .where(GlobalTradingPartner.active.is_(True))
            .limit(1)
        )
        resolved_tenant_id = result.scalar_one_or_none()
        if resolved_tenant_id is not None:
            tenant_id = resolved_tenant_id
    except Exception as e:
        logger.warning("tenant_resolution_failed", error=str(e), as2_to=as2_msg.as2_to)

    logger = logger.bind(message_id=as2_msg.message_id, tenant_id=tenant_id)

    with tenant_context(tenant_id):
        partner_repo = TradingPartnerRepository(session)
        payload_repo = EdiMessageRepository(session)

        partner = await partner_repo.find_by_as2_id(as2_msg.as2_from)
        if not partner:
            metrics.increment("as2_verify_errors_total", labels={"tenant_id": str(tenant_id)})
            logger.warning("as2_unknown_partner", as2_from=as2_msg.as2_from)
            disposition = (
                "automatic-action/MDN-sent-automatically; failed/insufficient-message-security"
            )
            mdn = generate_mdn(original_message=as2_msg, disposition=disposition)
            return Response(
                content=render_mdn_report(mdn),
                status_code=200,
                media_type='multipart/report; report-type=disposition-notification; boundary="----=_MDNBoundary"',
                headers={"AS2-Version": "1.2", "EDIINT-Features": "multiple-attachments"},
            )

        metrics.increment(
            "as2_messages_received_total",
            labels={
                "tenant_id": str(tenant_id),
                "as2_from": as2_msg.as2_from,
                "as2_to": as2_msg.as2_to,
            },
        )
        logger.info(
            "as2_message_received", is_encrypted=as2_msg.is_encrypted, is_signed=as2_msg.is_signed
        )

        processed_payload = as2_msg.payload
        disposition = "automatic-action/MDN-sent-automatically; processed"

        # --- Step 2: Decrypt ---
        if as2_msg.is_encrypted:
            with tracer.start_span("as2.decrypt") as span:
                try:
                    private_key_pem = get_host_private_key()
                    host_cert_pem = get_host_certificate()
                    if not private_key_pem:
                        raise ValueError("Host private key not found for decryption.")
                    if not host_cert_pem:
                        raise ValueError("Host public certificate not found for decryption.")

                    processed_payload = decrypt_payload(raw_body, private_key_pem, host_cert_pem)
                    logger.info("as2_decrypt_success")
                except Exception as e:
                    span.record_exception(e)
                    span.set_status_error("Decryption failed")
                    metrics.increment(
                        "as2_decrypt_errors_total", labels={"tenant_id": str(tenant_id)}
                    )
                    logger.error("as2_decrypt_failed", error=str(e))
                    disposition = (
                        "automatic-action/MDN-sent-automatically; failed/decryption-failed"
                    )

        # --- Step 3: Verify Signature ---
        if as2_msg.is_signed and "failed" not in disposition:
            with tracer.start_span("as2.verify_signature") as span:
                if not partner.public_cert_pem:
                    span.set_status_error("Partner certificate missing")
                    metrics.increment(
                        "as2_verify_errors_total", labels={"tenant_id": str(tenant_id)}
                    )
                    logger.warning("as2_partner_cert_missing", as2_from=as2_msg.as2_from)
                    disposition = "automatic-action/MDN-sent-automatically; failed/insufficient-message-security"
                else:
                    partner_cert = partner.public_cert_pem.encode("utf-8")
                    is_valid, verified_payload = verify_signature(processed_payload, partner_cert)
                    if not is_valid:
                        span.set_status_error("Signature invalid")
                        metrics.increment(
                            "as2_verify_errors_total", labels={"tenant_id": str(tenant_id)}
                        )
                        logger.warning("as2_signature_invalid")
                        disposition = (
                            "automatic-action/MDN-sent-automatically; failed/authentication-failed"
                        )
                    else:
                        processed_payload = verified_payload
                        logger.info("as2_signature_verified")

        # --- Step 4: Stream Payload to S3 ---
        with tracer.start_span("as2.s3_upload"):
            as2_msg.payload = processed_payload
            storage_uri = await s3.upload(tenant_id, as2_msg.message_id, processed_payload)

        # --- Step 5: Persist Metadata to DB ---
        with tracer.start_span("as2.db_persist"):
            status = "ERROR" if "failed" in disposition else "RECEIVED"
            trace_id = uuid.uuid4()
            await payload_repo.save_message(
                trace_id=trace_id,
                direction="INBOUND",
                connection_type="AS2",
                trading_partner_id=partner.id,  # type: ignore[arg-type]
                s3_key=storage_uri,
                status=status,
                as2_message_id=as2_msg.message_id,
            )

        # --- Step 6: Generate MDN ---
        with tracer.start_span("as2.generate_mdn"):
            mdn = generate_mdn(original_message=as2_msg, disposition=disposition)
            report_bytes = render_mdn_report(mdn)

        duration = time.perf_counter() - start_time
        metrics.observe(
            "as2_message_processing_seconds", duration, labels={"tenant_id": str(tenant_id)}
        )
        metrics.increment(
            "as2_mdn_sent_total",
            labels={
                "tenant_id": str(tenant_id),
                "disposition": "processed" if "failed" not in disposition else "failed",
            },
        )
        logger.info("as2_mdn_sent", disposition=disposition, duration_ms=round(duration * 1000, 2))

        return Response(
            content=report_bytes,
            status_code=200,
            media_type='multipart/report; report-type=disposition-notification; boundary="----=_MDNBoundary"',
            headers={"AS2-Version": "1.2", "EDIINT-Features": "multiple-attachments"},
        )
