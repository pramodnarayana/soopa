from functools import lru_cache
from typing import Annotated, Any, cast

from database.types import GlobalSession
from dependency_injector.wiring import Provide, inject
from edi.adapters.outbound.database.session import get_global_session
from edi.adapters.outbound.pubsub.publisher_factory import create_edi_pipeline_publisher
from edi.bootstrap.container import Container
from edi.config.models import EdiAwsSettings, EdiDataPlaneSqsSettings
from edi.ports.outbound.as2_tester import AS2TesterPort
from edi.ports.outbound.sftp_tester import SftpTesterPort
from edi.ports.outbound.tenant_repository import TenantRepositoryPort
from fastapi import Depends
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
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


@lru_cache
def get_outbox_publisher() -> OutboxPublisherPort:
    kwargs: dict[str, Any] = {}
    sqs = EdiDataPlaneSqsSettings(**kwargs)
    aws = EdiAwsSettings(**kwargs)
    publisher = create_edi_pipeline_publisher(
        compute_queue_url=sqs.compute_queue_url,
        orchestrator_queue_url=sqs.orchestrator_queue_url,
        deliver_queue_url=sqs.deliver_queue_url,
        region_name=aws.resolved_region,
        endpoint_url=aws.endpoint_url,
    )
    return publisher
