from database.router import DatabaseRouter

"""
Production-ready FastAPI application for the EDI AS2 Server.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from edi.adapters.outbound.database.s3 import Aioboto3PayloadStorage
from edi.config.settings import get_settings
from fastapi import FastAPI
from observability import (
    ObservabilityProvider,
    OtelMetrics,
    OtelTracer,
    StructlogLogger,
)

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

    s3_storage = Aioboto3PayloadStorage(
        bucket=settings.s3.bucket,
        region=settings.s3.region,
        endpoint_url=settings.s3.endpoint_url,
        access_key_id=settings.s3.access_key_id,
        secret_access_key=settings.s3.secret_access_key,
    )
    app.state.s3_storage = s3_storage

    logger = ObservabilityProvider.logger(__name__)

    # Initialize the global DatabaseRouter and mount it to app state
    db_router = DatabaseRouter(
        settings.database.global_url,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
    )
    app.state.db_router = db_router
    print("LIFESPAN: DB Router initialized")

    logger.info("as2_server_started", env=settings.env)
    yield
    logger.info("as2_server_stopped")
    if hasattr(app.state, "db_router"):
        await app.state.db_router.close_all()


app = FastAPI(title="AS2 Server", version="1.0.0", lifespan=lifespan)

app.include_router(ops.router)
app.include_router(as2.router)
