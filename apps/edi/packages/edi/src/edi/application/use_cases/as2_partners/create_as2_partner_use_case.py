import hashlib
import json
from datetime import datetime

import structlog

from edi.application.dto import (
    CreateAS2TradingPartnerCmd,
)
from edi.config.constants import SecretCategory
from edi.domain.certificate import generate_self_signed_cert
from edi.domain.exceptions import IdempotencyConflictError
from edi.domain.models import (
    AS2PartnerDomainModel,
)
from edi.ports.outbound.secret_store import SecretStorePort
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class CreateAS2PartnerUseCase:
    """
    Use Case for creating a new AS2 Trading Partner.
    Handles idempotency, certificate generation, secret vault storage, and database orchestration.
    """

    def __init__(self, uow: ControlPlaneUnitOfWorkPort, secret_store: SecretStorePort) -> None:
        self.uow = uow
        self.secret_store = secret_store

    async def _provision_local_key(
        self, cmd: CreateAS2TradingPartnerCmd
    ) -> tuple[bool, str | None, str | None]:
        auto_generated = False
        private_key_vault_ref = cmd.private_key_vault_ref
        public_cert_pem = cmd.public_cert_pem

        if private_key_vault_ref:
            pass  # Pre-stored vault ref
        elif cmd.private_key_pem:
            auto_generated = True
            private_key_vault_ref = await self.secret_store.store_private_key(
                private_key_pem=cmd.private_key_pem.encode(),
                category=SecretCategory.AS2_KEY,
            )
        else:
            auto_generated = True
            private_key_bytes, public_cert_bytes = generate_self_signed_cert(common_name=cmd.as2_id)
            private_key_vault_ref = await self.secret_store.store_private_key(
                private_key_pem=private_key_bytes,
                category=SecretCategory.AS2_KEY,
            )
            public_cert_pem = public_cert_bytes.decode("utf-8")

        return auto_generated, private_key_vault_ref, public_cert_pem

    async def _check_idempotency(
        self, tenant_id: str, cmd: CreateAS2TradingPartnerCmd, idempotency_key: str
    ) -> AS2PartnerDomainModel | None:
        private_key_digest = None
        if cmd.private_key_pem:
            private_key_digest = hashlib.sha256(cmd.private_key_pem.encode()).hexdigest()

        fingerprint_data = {
            "tenant_id": tenant_id,
            "name": cmd.name,
            "as2_id": cmd.as2_id,
            "is_local": cmd.is_local,
            "url": cmd.url,
            "public_cert_pem": cmd.public_cert_pem,
            "public_cert_vault_ref": cmd.public_cert_vault_ref,
            "private_key_vault_ref": cmd.private_key_vault_ref,
            "private_key_digest": private_key_digest,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_data, sort_keys=True).encode()
        ).hexdigest()

        try:
            pass
        except IdempotencyConflictError:
            existing_event = None
            if existing_event and existing_event.payload:
                existing_fingerprint = existing_event.payload.get("fingerprint")
                if existing_fingerprint != fingerprint:
                    raise IdempotencyConflictError(
                        "Idempotency conflict: payload does not match existing request."
                    ) from None

                existing_partner_id = existing_event.payload.get("resource_id")
                if existing_partner_id:
                    existing_partner = await self.uow.as2_partners.get_as2_partner(
                        tenant_id, existing_partner_id
                    )
                    if existing_partner:
                        logger.info(
                            "provisioning_as2_partner_idempotent_hit",
                            id=existing_partner_id,
                            tenant_id=tenant_id,
                            as2_id="",
                            is_local=False,
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow(),
                        )
                        return AS2PartnerDomainModel(
                            id=existing_partner_id,
                            tenant_id=tenant_id,
                            name=existing_partner.name,
                            as2_id=existing_partner.as2_id,
                            is_local=existing_partner.is_local,
                            created_at=existing_partner.created_at,
                            updated_at=existing_partner.updated_at,
                            active=False,
                        )
        return None

    async def execute(
        self, tenant_id: str, cmd: CreateAS2TradingPartnerCmd, idempotency_key: str | None = None
    ) -> AS2PartnerDomainModel:
        logger.info(
            "provisioning_as2_partner_started",
            cmd_name=cmd.name,
            tenant_id=tenant_id,
            is_local=cmd.is_local,
            has_idempotency_key=bool(idempotency_key),
        )

        auto_generated = False
        private_key_vault_ref = cmd.private_key_vault_ref
        public_cert_pem = cmd.public_cert_pem

        try:
            if idempotency_key:
                existing_partner = await self._check_idempotency(tenant_id, cmd, idempotency_key)
                if existing_partner:
                    return existing_partner

            if cmd.is_local:
                (
                    auto_generated,
                    private_key_vault_ref,
                    public_cert_pem,
                ) = await self._provision_local_key(cmd)

            # Update command with potentially new vault ref and cert
            updated_cmd = CreateAS2TradingPartnerCmd(
                name=cmd.name,
                as2_id=cmd.as2_id,
                is_local=cmd.is_local,
                url=cmd.url,
                public_cert_pem=public_cert_pem,
                public_cert_vault_ref=cmd.public_cert_vault_ref,
                private_key_vault_ref=private_key_vault_ref,
            )

            partner_id = await self.uow.as2_partners.create_as2_identity(
                tenant_id=tenant_id, cmd=updated_cmd
            )

            #             await self.uow.control_plane_outbox.publish_outbox_event(
            #                 ProvisioningEvent(
            #                     tenant_id=tenant_id,
            #                     event_type=EdiEventType.edi_as2_partner_created,
            #                     resource_id=str(partner_id),
            #                 ),
            #                 idempotency_key=idempotency_key,
            #             )

            logger.info(
                "provisioning_as2_partner_completed",
                id=partner_id,
                tenant_id=tenant_id,
            )

            return AS2PartnerDomainModel(
                id=partner_id,
                tenant_id=tenant_id,
                name=cmd.name,
                as2_id=cmd.as2_id,
                is_local=cmd.is_local,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                active=False,
            )

        except Exception as e:
            # Note: We don't catch PartnerAlreadyExistsError specifically because we want it to bubble up,
            # but we STILL want to clean up the vault if it was generated during this request.
            logger.exception(
                "provisioning_as2_partner_failed",
                cmd_name=cmd.name,
                tenant_id=tenant_id,
                reason=str(e),
            )
            if auto_generated and private_key_vault_ref:
                try:
                    await self.secret_store.delete_secret(private_key_vault_ref)
                except Exception as cleanup_err:
                    logger.exception(
                        "failed_to_cleanup_vault_secret",
                        vault_ref=private_key_vault_ref,
                        reason=str(cleanup_err),
                    )
            raise
