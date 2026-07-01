from typing import Annotated

from database.session import get_session
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .adapters.repository import (
    AS2TenantRepositoryAdapter,
    EdiMessageRepositoryAdapter,
    TradingPartnerRepositoryAdapter,
)
from .adapters.vault import EnvironmentVaultService
from .core.receive_as2 import ReceiveAS2UseCase

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_receive_as2_use_case(
    request: Request,
    session: SessionDep,
) -> ReceiveAS2UseCase:
    """
    Dependency injection for the ReceiveAS2UseCase.
    Wiring the ports to their adapters.
    """
    s3_storage = getattr(request.app.state, "s3_storage", None)
    if not s3_storage:
        raise HTTPException(status_code=503, detail="S3 Storage not initialized")

    return ReceiveAS2UseCase(
        tenant_repo=AS2TenantRepositoryAdapter(session),
        partner_repo=TradingPartnerRepositoryAdapter(session),
        message_repo=EdiMessageRepositoryAdapter(session),
        storage=s3_storage,
        vault=EnvironmentVaultService(),
    )
