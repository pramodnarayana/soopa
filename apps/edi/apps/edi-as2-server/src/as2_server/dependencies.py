from typing import Annotated

from edi.adapters.outbound.database.control_plane.uow import SqlAlchemyControlPlaneUnitOfWork
from edi.adapters.outbound.database.session import get_global_session, get_session
from edi.adapters.outbound.database.uow_factory import SqlAlchemyDataPlaneUnitOfWorkFactory
from edi.application.use_cases.process_inbound_as2_message_use_case import (
    ProcessInboundAs2MessageUseCase,
)
from fastapi import Depends, HTTPException, Request
from secret_store.ports.secret_store_port import SecretStorePort
from secret_store.provider import SecretStoreProvider
from sqlalchemy.ext.asyncio import AsyncSession


def get_vault_service() -> SecretStorePort:
    return SecretStoreProvider.create()


VaultDep = Annotated[SecretStorePort, Depends(get_vault_service)]

GlobalSessionDep = Annotated[AsyncSession, Depends(get_global_session)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_receive_as2_use_case(
    request: Request,
    global_session: GlobalSessionDep,
    vault: VaultDep,
) -> ProcessInboundAs2MessageUseCase:
    """
    Dependency injection for the central Enterprise AS2 Use Case.
    """
    if not hasattr(request.app.state, "s3_storage") or not request.app.state.s3_storage:
        raise HTTPException(status_code=503, detail="S3 Storage not initialized")
    s3_storage = request.app.state.s3_storage

    if not hasattr(request.app.state, "db_router") or not request.app.state.db_router:
        raise HTTPException(status_code=503, detail="Database router not initialized")
    db_router = request.app.state.db_router

    if not hasattr(request.app.state, "publisher") or not request.app.state.publisher:
        raise HTTPException(status_code=503, detail="Publisher not initialized")
    publisher = request.app.state.publisher

    if not hasattr(request.app.state, "crypto_service") or not request.app.state.crypto_service:
        raise HTTPException(status_code=503, detail="Crypto service not initialized")
    crypto_service = request.app.state.crypto_service

    control_plane_uow = SqlAlchemyControlPlaneUnitOfWork(global_session)
    dp_factory = SqlAlchemyDataPlaneUnitOfWorkFactory(
        storage=s3_storage, resolver=request.app.state.tenant_resolver, db_router=db_router
    )

    return ProcessInboundAs2MessageUseCase(
        control_plane_uow=control_plane_uow,
        dp_factory=dp_factory,
        secret_store=vault,
        crypto_service=crypto_service,
        publisher=publisher,
    )
