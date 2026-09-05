from typing import Annotated, Any, cast

from database.types import GlobalSession
from dependency_injector.wiring import Provide, inject
from edi.adapters.outbound.database.session import get_global_session
from edi.application.use_cases.process_inbound_as2_message_use_case import (
    ProcessInboundAs2MessageUseCase as ProcessInboundAS2MessageUseCase,
)
from edi.bootstrap.container import Container
from edi.ports.outbound.as2_tester import AS2TesterPort
from edi.ports.outbound.sftp_tester import SftpTesterPort
from edi.ports.outbound.tenant_repository import TenantRepositoryPort
from fastapi import Depends, Request
from secret_store.ports.secret_store_port import SecretStorePort


@inject
def get_sftp_tester(sftp_tester: Any = Depends(Provide[Container.sftp_tester])) -> SftpTesterPort:
    """Returns the Paramiko-based SFTP connection tester."""
    return cast(SftpTesterPort, sftp_tester)


@inject
def get_as2_tester(as2_tester: Any = Depends(Provide[Container.as2_tester])) -> AS2TesterPort:
    """Returns the httpx-based AS2 connection tester."""
    return cast(AS2TesterPort, as2_tester)


@inject
def get_secret_store(vault_port: Any = Depends(Provide[Container.vault_port])) -> SecretStorePort:
    return cast(SecretStorePort, vault_port)


@inject
def get_tenant_repo(
    session: Annotated[GlobalSession, Depends(get_global_session)],
    tenant_repo_factory: Any = Depends(Provide[Container.tenant_repo.provider]),
) -> TenantRepositoryPort:
    return cast(TenantRepositoryPort, tenant_repo_factory(session=session))


@inject
def get_as2_receiver_service(
    request: Request,
    global_session: Annotated[GlobalSession, Depends(get_global_session)],
    service_factory: Any = Depends(Provide[Container.as2_receiver_service.provider]),
    cp_uow_factory: Any = Depends(Provide[Container.cp_uow.provider]),
    dp_factory_provider: Any = Depends(Provide[Container.dp_factory.provider]),
) -> ProcessInboundAS2MessageUseCase:
    control_plane_uow = cp_uow_factory(global_session=global_session)
    dp_factory = dp_factory_provider(
        global_session=global_session, db_router=request.app.state.db_router
    )
    return cast(
        ProcessInboundAS2MessageUseCase,
        service_factory(
            control_plane_uow=control_plane_uow,
            dp_factory=dp_factory,
        ),
    )
