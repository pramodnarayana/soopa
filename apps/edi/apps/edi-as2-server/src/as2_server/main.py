from database.router import DatabaseRouter
from edi.adapters.outbound.database.tenant_resolver import TenantResolver

"""
Production-ready FastAPI application for the EDI AS2 Server.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from edi.adapters.outbound.pubsub.publisher_factory import create_edi_pipeline_publisher
from edi.adapters.outbound.security.smime_crypto_service import SmimeCryptoService
from fastapi import FastAPI
from observability import (
    ObservabilityProvider,
    OtelMetrics,
    OtelTracer,
    StructlogLogger,
)
from storage.provider import StorageProvider

from as2_server.settings import get_settings

from .adapters.inbound.http.routers import as2, ops


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    ObservabilityProvider.configure(
        tracer=OtelTracer(
            service_name=settings.otel.service_name,
            otlp_endpoint=settings.otel.exporter_otlp_endpoint,
        ),
        metrics=OtelMetrics(
            service_name=settings.otel.service_name,
            otlp_endpoint=settings.otel.exporter_otlp_endpoint,
        ),
        logger=StructlogLogger(name="edi", log_level=settings.log_level),
    )

    s3_storage = StorageProvider.create_payload_storage()
    app.state.s3_storage = s3_storage

    publisher = create_edi_pipeline_publisher(
        compute_queue_url=settings.sqs.compute_queue_url,
        orchestrator_queue_url=settings.sqs.orchestrator_queue_url,
        deliver_queue_url=settings.sqs.deliver_queue_url,
        region_name=settings.aws.resolved_region,
        endpoint_url=settings.aws.endpoint_url,
    )
    app.state.publisher = publisher
    app.state.crypto_service = SmimeCryptoService()

    logger = ObservabilityProvider.logger(__name__)

    # Initialize the global DatabaseRouter and mount it to app state
    db_router = DatabaseRouter(
        global_db_url=settings.database.global_url,
        shard_overrides=settings.database.shard_overrides,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
    )
    app.state.db_router = db_router
    app.state.tenant_resolver = TenantResolver(db_router=db_router)
    logger.info("as2_server_db_router_initialized")

    logger.info("as2_server_started", env=settings.env)
    yield
    logger.info("as2_server_stopped")
    if hasattr(app.state, "db_router"):
        await app.state.db_router.close_all()


app = FastAPI(title="AS2 Server", version="1.0.0", lifespan=lifespan)

app.include_router(ops.router)
app.include_router(as2.router)
