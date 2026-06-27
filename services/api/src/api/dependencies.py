import os
from collections.abc import AsyncGenerator
from functools import lru_cache

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.adapters.sqs_queue import SQSMessageQueueAdapter
from api.ports.message_queue import MessageQueuePort


@lru_cache
def get_message_queue() -> MessageQueuePort:
    """
    Dependency provider for the MessageQueuePort.
    Returns the SQS implementation.
    """
    endpoint_url = os.getenv("AWS_ENDPOINT_URL")
    return SQSMessageQueueAdapter(endpoint_url=endpoint_url)


async def get_global_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency provider for a SQLAlchemy AsyncSession pointing to the Global DB.
    """
    db_router = request.app.state.db_router
    async for session in db_router.get_global_session():
        yield session
