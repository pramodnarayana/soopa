import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from secret_store.ports.secret_store_port import SecretStorePort
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from edi.config.constants import SecretCategory
from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.domain.exceptions import IdempotencyConflictError
from edi.domain.models.as2 import AS2PartnerDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CreateAS2TradingPartnerCmd:
    name: str
    as2_id: str
    is_local: bool = False
    url: str | None = None
    public_cert_pem: str | None = None
    private_key_pem: str | None = None
    public_cert_vault_ref: str | None = None
    private_key_vault_ref: str | None = None


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
        private_key_vault_ref = cmd.private_key_vault_ref
        public_cert_pem = cmd.public_cert_pem

        is_new_key = False
        if private_key_vault_ref:
            pass  # Pre-stored vault ref — use as-is
        elif cmd.private_key_pem:
            # User explicitly provided a private key — store it in vault
            private_key_vault_ref = await self.secret_store.store_private_key(
                private_key_pem=cmd.private_key_pem.encode(),
                category=SecretCategory.AS2_KEY,
            )
            is_new_key = True
        else:
            # No key material provided. Certificate generation is an explicit user action
            # via POST /as2/certificates/generate. This endpoint must never auto-generate.
            raise ValueError(
                "No private key material provided for a local AS2 partner. "
                "Use the 'Generate Certificate' action first and supply the resulting "
                "private_key_vault_ref, or provide your own private_key_pem."
            )

        if cmd.public_cert_pem and not private_key_vault_ref:
            # Defensive guard: cert without key is always an invalid configuration.
            raise ValueError(
                "A public_cert_pem was provided without a corresponding private key. "
                "Supply private_key_pem or private_key_vault_ref."
            )

        return is_new_key, private_key_vault_ref, public_cert_pem

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
            await self.uow.control_plane_outbox.create_reservation(
                tenant_id, idempotency_key, fingerprint
            )
        except IdempotencyConflictError:
            existing_event = await self.uow.control_plane_outbox.get_event_by_idempotency_key(
                idempotency_key
            )
            if existing_event and existing_event.payload:
                existing_fingerprint = (
                    str(existing_event.payload.get("fingerprint"))
                    if existing_event.payload.get("fingerprint")
                    else None
                )
                if existing_fingerprint != fingerprint:
                    raise IdempotencyConflictError(
                        "Idempotency conflict: payload does not match existing request."
                    ) from None

                existing_partner_id_val = existing_event.payload.get("resource_id")
                if existing_partner_id_val:
                    existing_partner_id = str(existing_partner_id_val)
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
                            created_at=datetime.now(UTC),
                            updated_at=datetime.now(UTC),
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

            partner_id = generate_id(AS2PartnerDomainModel.ID_PREFIX)

            aggregate = AS2PartnerDomainModel(
                id=partner_id,
                tenant_id=tenant_id,
                name=cmd.name,
                as2_id=cmd.as2_id,
                is_local=cmd.is_local,
                url=cmd.url,
                public_cert_pem=public_cert_pem,
                public_cert_vault_ref=cmd.public_cert_vault_ref,
                private_key_vault_ref=private_key_vault_ref,
                created_at=datetime.now(UTC).replace(tzinfo=None),
                updated_at=datetime.now(UTC).replace(tzinfo=None),
                active=False,
            )

            event = ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partner_created,
                resource_id=partner_id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.GENERIC),
            )

            aggregate.add_domain_event(event)

            await self.uow.as2_partners.save(aggregate)

            logger.info(
                "provisioning_as2_partner_completed",
                id=partner_id,
                tenant_id=tenant_id,
            )

            return aggregate

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
