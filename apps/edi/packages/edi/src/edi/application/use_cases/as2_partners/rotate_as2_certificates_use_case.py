from dataclasses import dataclass

import structlog
from secret_store.ports.secret_store_port import SecretStorePort
from seedwork.domain.exceptions import Result

from edi.config.constants import SecretCategory
from edi.domain.exceptions import (
    EdiError,
    InvalidCertificateActionEdiError,
    MissingCertificateEdiError,
    OrchestrationError,
    PartnerNotFoundEdiError,
)
from edi.domain.partner.as2.enums import CertificateRotationAction
from edi.domain.partner.as2.partner import AS2Partner
from edi.ports.outbound.certificate_generator_port import CertificateGeneratorPort
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RotateAS2CertificateCmd:
    action: str | None = None
    public_cert_pem: str | None = None
    private_key_pem: str | None = None
    public_cert_vault_ref: str | None = None
    private_key_vault_ref: str | None = None


class RotateAS2CertificatesUseCase:
    """Use Case for rotating AS2 Trading Partner certificates."""

    def __init__(
        self,
        uow: ControlPlaneUnitOfWorkPort,
        certificate_generator: CertificateGeneratorPort,
    ) -> None:
        self.uow = uow
        self._certificate_generator = certificate_generator

    async def _provision_certificates(
        self,
        partner: AS2Partner,
        action: CertificateRotationAction,
        cmd: RotateAS2CertificateCmd,
        secret_store: SecretStorePort,
    ) -> Result[tuple[str, str | None], EdiError]:
        public_cert_pem = cmd.public_cert_pem
        private_key_vault_ref: str | None = None

        if partner.is_local:
            if action == CertificateRotationAction.GENERATE:
                private_key_bytes, public_cert_bytes = (
                    self._certificate_generator.generate_self_signed_cert(
                        common_name=partner.as2_id
                    )
                )
                private_key_vault_ref = await secret_store.store_private_key(
                    private_key_pem=private_key_bytes,
                    category=SecretCategory.AS2_KEY,
                )
                public_cert_pem = public_cert_bytes.decode("utf-8")
            elif action == CertificateRotationAction.UPLOAD:
                if not cmd.private_key_pem or not cmd.public_cert_pem:
                    return Result.fail(
                        MissingCertificateEdiError.with_message(
                            "Both public_cert_pem and private_key_pem required for upload."
                        )
                    )
                private_key_vault_ref = await secret_store.store_private_key(
                    private_key_pem=cmd.private_key_pem.encode("utf-8"),
                    category=SecretCategory.AS2_KEY,
                )
        else:
            if not cmd.public_cert_pem:
                return Result.fail(
                    MissingCertificateEdiError.with_message(
                        "public_cert_pem required for remote partners."
                    )
                )

        if not public_cert_pem:
            return Result.fail(
                MissingCertificateEdiError.with_message(
                    "public_cert_pem must not be None at this point."
                )
            )

        return Result.ok((public_cert_pem, private_key_vault_ref))

    async def execute(
        self,
        tenant_id: str,
        partner_id: str,
        cmd: RotateAS2CertificateCmd,
        secret_store: SecretStorePort,
        idempotency_key: str | None = None,
    ) -> Result[AS2Partner, EdiError]:
        logger.info(
            "rotate_as2_certificates_started",
            id=partner_id,
            tenant_id=tenant_id,
        )

        partner = await self.uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not partner:
            not_found = PartnerNotFoundEdiError.for_id(partner_id, tenant_id)
            logger.error(
                "rotate_as2_certificates_partner_not_found",
                id=partner_id,
                tenant_id=tenant_id,
                error_code=not_found.code,
            )
            return Result.fail(not_found)

        try:
            action = CertificateRotationAction(str(cmd.action))
        except ValueError:
            bad_action = InvalidCertificateActionEdiError.for_action(str(cmd.action))
            logger.error(
                "rotate_as2_certificates_invalid_action",
                id=partner_id,
                tenant_id=tenant_id,
                action=cmd.action,
                error_code=bad_action.code,
            )
            return Result.fail(bad_action)

        cert_res = await self._provision_certificates(partner, action, cmd, secret_store)
        if cert_res.is_err:
            cert_err = cert_res.unwrap_err()
            logger.error(
                "rotate_as2_certificates_missing_material",
                id=partner_id,
                tenant_id=tenant_id,
                error_code=cert_err.code,
                reason=cert_err.message,
            )
            return Result.fail(cert_err)

        public_cert_pem, private_key_vault_ref = cert_res.unwrap()

        try:
            rot_res = partner.rotate_certificate(
                public_cert_pem=public_cert_pem,
                private_key_vault_ref=private_key_vault_ref,
                public_cert_vault_ref=None,
                idempotency_key=idempotency_key,
            )
            if rot_res.is_err:
                if private_key_vault_ref:
                    await secret_store.delete_secret(private_key_vault_ref)
                domain_err = rot_res.unwrap_err()
                logger.error(
                    "rotate_as2_certificates_domain_rejected",
                    id=partner_id,
                    tenant_id=tenant_id,
                    error_code=domain_err.code,
                    reason=domain_err.message,
                )
                return Result.fail(domain_err)

            await self.uow.as2_partners.save(partner)

            persisted = await self.uow.as2_partners.get_as2_partner(tenant_id, partner_id)
            if persisted:
                partner = persisted

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

        return Result.ok(partner)
