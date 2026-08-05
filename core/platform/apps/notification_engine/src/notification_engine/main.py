import logging
import os
import sys
from contextlib import asynccontextmanager

import punq
from dotenv import load_dotenv
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .adapters.outbound.delivery_dispatcher import StrategyDeliveryDispatcher
from .adapters.outbound.template_renderer import Jinja2TemplateRenderer
from .adapters.outbound.template_repository import SqlAlchemyTemplateRepository
from .api.router import router
from .application.dispatch_use_case import DispatchNotificationUseCase
from .ports.interfaces import DeliveryDispatcherPort, TemplateRendererPort, TemplateRepositoryPort

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

container = punq.Container()

from collections.abc import AsyncGenerator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Load .env file from project root
    dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../../.env"))
    load_dotenv(dotenv_path)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL is not set")
        sys.exit(1)

    # Convert to asyncpg
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    from .adapters.outbound.channels import (
        EmailDeliveryStrategy,
        InAppDeliveryStrategy,
        SlackDeliveryStrategy,
    )

    # Register dependencies
    container.register(async_sessionmaker[AsyncSession], instance=session_factory)
    container.register(TemplateRepositoryPort, SqlAlchemyTemplateRepository)
    container.register(TemplateRendererPort, Jinja2TemplateRenderer)

    container.register(EmailDeliveryStrategy)
    container.register(InAppDeliveryStrategy)
    container.register(SlackDeliveryStrategy)
    container.register(DeliveryDispatcherPort, StrategyDeliveryDispatcher)
    container.register(DispatchNotificationUseCase)

    yield

    await engine.dispose()
    logger.info("Database engine disposed.")


app = FastAPI(title="Notification Engine", lifespan=lifespan)
app.include_router(router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("notification_engine.main:app", host="0.0.0.0", port=3001, reload=True)
