from typing import Annotated

from edi.adapters.outbound.database.session import get_global_session, get_session
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .adapters.outbound.repository import (
    AS2TenantRepositoryAdapter,
    EdiMessageRepositoryAdapter,
    TradingPartnerRepositoryAdapter,
)
from .adapters.outbound.vault import EnvironmentVaultService
from .application.use_cases.receive_as2 import ReceiveAS2UseCase

GlobalSessionDep = Annotated[AsyncSession, Depends(get_global_session)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_receive_as2_use_case(
    request: Request,
    global_session: GlobalSessionDep,
    session: SessionDep,
) -> ReceiveAS2UseCase:
    """
    Dependency injection for the ReceiveAS2UseCase.
    Wiring the ports to their adapters.
    """
    s3_storage = getattr(request.app.state, "s3_storage", None)
    if not s3_storage:
        raise HTTPException(status_code=503, detail="S3 Storage not initialized")

    db_router = getattr(request.app.state, "db_router", None)

    return ReceiveAS2UseCase(
        tenant_repo=AS2TenantRepositoryAdapter(global_session),
        partner_repo=TradingPartnerRepositoryAdapter(global_session),
        message_repo=EdiMessageRepositoryAdapter(session),
        storage=s3_storage,
        vault=EnvironmentVaultService(),
        db_router=db_router,
        global_session=global_session,
    )
