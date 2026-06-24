"""
Production-ready FastAPI application for the EDI AS2 Server.
"""

import time
from contextlib import asynccontextmanager
from typing import Annotated

from as2_core import (
    decrypt_payload,
    generate_mdn,
    parse_as2_request,
    render_mdn_report,
    verify_signature,
)
from config.settings import get_settings
from database.repository import (
    AS2PayloadRepository,
    HostIdentityRepository,
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
s3_storage: IPayloadStorage = None


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    from database.connection import engine
    from database.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("edi_as2_server_started", env=settings.env)
    yield
    logger.info("edi_as2_server_stopped")


app = FastAPI(title="AS2 Server", version="1.0.0", lifespan=lifespan)
SessionDep = Annotated[AsyncSession, Depends(get_session)]


# Provide S3 as a FastAPI dependency for easy mocking in tests
def get_s3_storage() -> IPayloadStorage:
    return s3_storage


S3Dep = Annotated[IPayloadStorage, Depends(get_s3_storage)]


@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
async def ready():
    return {"status": "ready"}


@app.get("/metrics", tags=["ops"])
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/as2", tags=["as2"])
async def receive_as2(request: Request, session: SessionDep, s3: S3Dep):
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

    tenant_id = 1
    logger = logger.bind(message_id=as2_msg.message_id, tenant_id=tenant_id)

    with tenant_context(tenant_id):
        partner_repo = TradingPartnerRepository(session)
        payload_repo = AS2PayloadRepository(session)
        identity_repo = HostIdentityRepository(session)

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
                    private_key_pem = await identity_repo.get_host_private_key()
                    if not private_key_pem:
                        raise ValueError("Host private key not found in database for decryption.")

                    # Passing empty bytes for our cert since decrypt_payload expects it (legacy compat)
                    processed_payload = decrypt_payload(raw_body, private_key_pem, b"")
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
                partner = await partner_repo.find_by_as2_id(as2_msg.as2_from)
                if not partner or not partner.public_cert_pem:
                    span.set_status_error("Unknown trading partner")
                    metrics.increment(
                        "as2_verify_errors_total", labels={"tenant_id": str(tenant_id)}
                    )
                    logger.warning("as2_unknown_partner", as2_from=as2_msg.as2_from)
                    disposition = "automatic-action/MDN-sent-automatically; failed/insufficient-message-security"
                else:
                    is_valid, verified_payload = verify_signature(
                        processed_payload, partner.public_cert_pem.encode()
                    )
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
            await payload_repo.save_payload(
                message_id=as2_msg.message_id,
                direction="INBOUND",
                as2_from=as2_msg.as2_from,
                as2_to=as2_msg.as2_to,
                status=status,
                payload_storage_uri=storage_uri,
                raw_headers=str(headers),
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
