from typing import Annotated

from edi.adapters.outbound.database.session import get_global_session, get_session
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .adapters.outbound.database.edi_message_repository import (
    EdiMessageRepositoryAdapter,
    EdiMessageRepositoryFactory,
)
from .adapters.outbound.database.tenant_routing_repository import AS2TenantRepositoryAdapter
from .adapters.outbound.database.trading_partner_repository import TradingPartnerRepositoryAdapter
from .adapters.outbound.vault import EnvironmentVaultService
from .application.use_cases.receive_as2 import ReceiveAS2UseCase


def get_vault_service() -> EnvironmentVaultService:
    return EnvironmentVaultService()


VaultDep = Annotated[EnvironmentVaultService, Depends(get_vault_service)]

GlobalSessionDep = Annotated[AsyncSession, Depends(get_global_session)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_receive_as2_use_case(
    request: Request,
    global_session: GlobalSessionDep,
    session: SessionDep,
    vault: VaultDep,
) -> ReceiveAS2UseCase:
    """
    Dependency injection for the ReceiveAS2UseCase.
    Wiring the ports to their adapters.
    """
    if not hasattr(request.app.state, "s3_storage") or not request.app.state.s3_storage:
        raise HTTPException(status_code=503, detail="S3 Storage not initialized")
    s3_storage = request.app.state.s3_storage

    if not hasattr(request.app.state, "db_router") or not request.app.state.db_router:
        raise HTTPException(status_code=503, detail="Database router not initialized")
    db_router = request.app.state.db_router

    return ReceiveAS2UseCase(
        tenant_repo=AS2TenantRepositoryAdapter(global_session),
        partner_repo=TradingPartnerRepositoryAdapter(global_session),
        message_repo_factory=EdiMessageRepositoryFactory(),
        message_repo=EdiMessageRepositoryAdapter(session),
        storage=s3_storage,
        vault=vault,
        db_router=db_router,
        global_session=global_session,
    )
