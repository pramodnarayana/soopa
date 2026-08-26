from typing import Any

import structlog

from edi.application.dto import RotateAS2CertificateCmd
from edi.config.constants import SecretCategory
from edi.domain.certificate import generate_self_signed_cert
from edi.domain.exceptions import (
    InvalidCertificateActionError,
    MissingCertificateError,
    OrchestrationError,
    PartnerNotFoundError,
)
from edi.domain.models import AS2PartnerDomainModel
from edi.ports.outbound.secret_store import SecretStorePort
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class RotateAS2CertificatesUseCase:
    """
    Use Case for rotating AS2 Trading Partner certificates.
    """

    def __init__(self, uow: ControlPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def _provision_certificates(
        self,
        partner: Any,
        cmd: RotateAS2CertificateCmd,
        secret_store: SecretStorePort,
    ) -> tuple[str, str | None]:
        public_cert_pem = cmd.public_cert_pem
        private_key_vault_ref = None

        if partner.is_local:
            if cmd.action == "generate":
                private_key_bytes, public_cert_bytes = generate_self_signed_cert(
                    common_name=partner.as2_id
                )
                private_key_vault_ref = await secret_store.store_private_key(
                    private_key_pem=private_key_bytes,
                    category=SecretCategory.AS2_KEY,
                )
                public_cert_pem = public_cert_bytes.decode("utf-8")
            elif cmd.action == "upload":
                if not cmd.private_key_pem or not cmd.public_cert_pem:
                    raise MissingCertificateError(
                        "Both public_cert_pem and private_key_pem required for upload."
                    )
                private_key_vault_ref = await secret_store.store_private_key(
                    private_key_pem=cmd.private_key_pem.encode("utf-8"),
                    category=SecretCategory.AS2_KEY,
                )
        else:
            if not cmd.public_cert_pem:
                raise MissingCertificateError("public_cert_pem required for remote partners.")

        if not public_cert_pem:
            raise MissingCertificateError("public_cert_pem must not be None at this point.")

        return public_cert_pem, private_key_vault_ref

    async def execute(
        self,
        tenant_id: str,
        partner_id: str,
        cmd: RotateAS2CertificateCmd,
        secret_store: SecretStorePort,
        idempotency_key: str | None = None,
    ) -> AS2PartnerDomainModel:
        logger.info(
            "rotate_as2_certificates_started",
            id=partner_id,
            tenant_id=tenant_id,
        )

        partner = await self.uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not partner:
            raise PartnerNotFoundError(partner_id, tenant_id)

        # Validate action
        if cmd.action not in ("generate", "upload"):
            raise InvalidCertificateActionError(str(cmd.action))

        public_cert_pem, private_key_vault_ref = await self._provision_certificates(
            partner, cmd, secret_store
        )

        try:
            await self.uow.as2_partners.rotate_as2_certificates(
                tenant_id, partner_id, public_cert_pem, private_key_vault_ref
            )

            updated_partner = await self.uow.as2_partners.get_as2_partner(tenant_id, partner_id)
            if not updated_partner:
                raise PartnerNotFoundError(partner_id, tenant_id)

        #             await self.uow.control_plane_outbox.publish_outbox_event(
        #                 ProvisioningEvent(
        #                     tenant_id=tenant_id,
        #                     event_type=EdiEventType.edi_as2_partner_updated,
        #                     resource_id=str(partner_id),
        #                 ),
        #                 idempotency_key=idempotency_key,
        #             )

        except Exception as e:
            logger.exception(
                "certificate_rotation_failed",
                id=partner_id,
                tenant_id=tenant_id,
                reason=str(e),
            )
            if private_key_vault_ref:
                await secret_store.delete_secret(private_key_vault_ref)
            raise OrchestrationError(f"Failed to rotate certificates: {e!s}") from e

        logger.info(
            "rotate_as2_certificates_completed",
            id=partner_id,
            tenant_id=tenant_id,
        )

        return updated_partner
