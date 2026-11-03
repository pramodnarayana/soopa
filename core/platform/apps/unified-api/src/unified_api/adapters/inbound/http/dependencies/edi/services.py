from collections.abc import Callable, Mapping
from typing import Annotated

from database.types import GlobalSession
from dependency_injector.wiring import Provide, inject
from edi.application.use_cases.replay.stage_replay_processor import (
    EdiStageReplayProcessorPort,
    build_default_edi_stage_replay_processors,
)
from edi.bootstrap.container import Container
from edi.bootstrap.session import get_global_session
from edi.domain.transaction.enums import ReplayCheckpoint
from edi.ports.outbound.as2_tester import AS2TesterPort
from edi.ports.outbound.certificate_generator_port import CertificateGeneratorPort
from edi.ports.outbound.edi_ast_codec_port import EdiAstCodecPort
from edi.ports.outbound.sftp_tester import SftpTesterPort
from edi.ports.outbound.tenant_repository import TenantRepositoryPort
from fastapi import Depends
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from secret_store.ports.secret_store_port import SecretStorePort
from security.ports.cipher_port import CipherPort


@inject
def get_sftp_tester(
    sftp_tester: SftpTesterPort = Depends(Provide[Container.sftp_tester]),
) -> SftpTesterPort:
    """Returns the Paramiko-based SFTP connection tester."""
    return sftp_tester


@inject
def get_as2_tester(
    as2_tester: AS2TesterPort = Depends(Provide[Container.as2_tester]),
) -> AS2TesterPort:
    """Returns the httpx-based AS2 connection tester."""
    return as2_tester


@inject
def get_secret_store(
    vault_port: SecretStorePort = Depends(Provide[Container.vault_port]),
) -> SecretStorePort:
    return vault_port


@inject
def get_certificate_generator(
    certificate_generator: CertificateGeneratorPort = Depends(
        Provide[Container.certificate_generator]
    ),
) -> CertificateGeneratorPort:
    return certificate_generator


@inject
def get_field_encryption(
    field_encryption: CipherPort = Depends(Provide[Container.field_encryption]),
) -> CipherPort:
    return field_encryption


@inject
def get_edi_ast_codec(
    edi_ast_codec: EdiAstCodecPort = Depends(Provide[Container.edi_ast_codec]),
) -> EdiAstCodecPort:
    return edi_ast_codec


@inject
def get_tenant_repo(
    session: Annotated[GlobalSession, Depends(get_global_session)],
    tenant_repo_factory: Callable[..., TenantRepositoryPort] = Depends(
        Provide[Container.tenant_repo.provider]
    ),
) -> TenantRepositoryPort:
    return tenant_repo_factory(session=session)


@inject
def get_outbox_publisher(
    publisher: OutboxPublisherPort = Depends(Provide[Container.outbox_publisher]),
) -> OutboxPublisherPort:
    return publisher


def get_edi_stage_replay_processors() -> Mapping[ReplayCheckpoint, EdiStageReplayProcessorPort]:
    return build_default_edi_stage_replay_processors()
