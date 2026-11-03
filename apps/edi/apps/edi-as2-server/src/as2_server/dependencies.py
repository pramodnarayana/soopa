from collections.abc import Callable
from functools import lru_cache
from typing import Annotated, Protocol

from database.router import DatabaseRouterPort
from edi.application.use_cases.process_inbound_as2_message_use_case import (
    ProcessInboundAs2MessageUseCase,
)
from edi.bootstrap.session import get_global_session, get_session
from edi.ports.outbound.crypto_service_port import CryptoServicePort
from edi.ports.outbound.tenant_port import TenantPort
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort
from edi.ports.outbound.uow_factory import DataPlaneUnitOfWorkFactoryPort
from fastapi import Depends, HTTPException, Request
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from secret_store.ports.secret_store_port import SecretStorePort
from secret_store.provider import SecretStoreProvider
from sqlalchemy.ext.asyncio import AsyncSession
from storage.ports.payload_storage_port import PayloadStoragePort

from as2_server.settings import get_settings


class DataPlaneUoWFactoryBuilderProtocol(Protocol):
    def __call__(
        self,
        *,
        storage: PayloadStoragePort,
        resolver: TenantPort,
        db_router: DatabaseRouterPort,
    ) -> DataPlaneUnitOfWorkFactoryPort: ...


@lru_cache
def get_vault_service() -> SecretStorePort:
    settings = get_settings()
    return SecretStoreProvider.get_secret_store(
        secrets_mount_path=settings.secrets.mount_path,
    )


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
    s3_storage: PayloadStoragePort | None = request.app.state.s3_storage
    if s3_storage is None:
        raise HTTPException(status_code=503, detail="S3 Storage not initialized")

    db_router: DatabaseRouterPort | None = request.app.state.db_router
    if db_router is None:
        raise HTTPException(status_code=503, detail="Database router not initialized")

    tenant_resolver: TenantPort | None = request.app.state.tenant_resolver
    if tenant_resolver is None:
        raise HTTPException(status_code=503, detail="Tenant resolver not initialized")

    publisher: OutboxPublisherPort | None = request.app.state.publisher
    if publisher is None:
        raise HTTPException(status_code=503, detail="Publisher not initialized")

    crypto_service: CryptoServicePort | None = request.app.state.crypto_service
    if crypto_service is None:
        raise HTTPException(status_code=503, detail="Crypto service not initialized")

    cp_uow_factory: Callable[[AsyncSession], ControlPlaneUnitOfWorkPort] = (
        request.app.state.cp_uow_factory
    )
    dp_uow_factory_cls: DataPlaneUoWFactoryBuilderProtocol = request.app.state.dp_uow_factory_cls

    control_plane_uow = cp_uow_factory(global_session)
    dp_factory = dp_uow_factory_cls(
        storage=s3_storage,
        resolver=tenant_resolver,
        db_router=db_router,
    )

    return ProcessInboundAs2MessageUseCase(
        control_plane_uow=control_plane_uow,
        dp_factory=dp_factory,
        secret_store=vault,
        crypto_service=crypto_service,
        publisher=publisher,
    )
