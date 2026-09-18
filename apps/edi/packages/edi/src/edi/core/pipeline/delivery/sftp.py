import contextlib
from collections.abc import Callable

import structlog
from secret_store.ports.secret_store_port import SecretStorePort

from edi.core.pipeline.delivery.base import BaseDeliveryStrategy
from edi.domain.enums import MessageStatus
from edi.domain.models.transactions import EdiMessageDomainModel
from edi.ports.outbound.field_encryption import FieldEncryptionPort
from edi.ports.outbound.sftp_delivery_port import SftpDeliveryPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class SftpDeliveryStrategy(BaseDeliveryStrategy):
    def __init__(
        self,
        uow_factory: Callable[[], contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]],
        sftp_delivery: SftpDeliveryPort,
        vault: SecretStorePort | None = None,
        field_encryption: FieldEncryptionPort | None = None,
    ) -> None:
        super().__init__(uow_factory, vault)
        self.sftp_delivery = sftp_delivery
        self.field_encryption = field_encryption

    async def deliver(
        self,
        trace_id: str,
        partner_id: str,
        edi_msg: EdiMessageDomainModel,
        idempotency_key: str | None = None,
    ) -> None:
        try:
            async with self.uow_factory() as uow, uow:
                partner = await uow.sftp_partners.get_sftp_partner(edi_msg.tenant_id, partner_id)
                if not partner:
                    raise ValueError(f"SFTP partner {partner_id} not found.")
                if not edi_msg.edi_data:
                    raise ValueError("Empty EDI data")
                raw_payload = edi_msg.edi_data.encode("utf-8")
                filename = f"{trace_id}.edi"

                password: str | None = None
                client_key: str | None = None

                if partner.password_encrypted and self.field_encryption:
                    password = self.field_encryption.decrypt(partner.password_encrypted)

                if not password and partner.credentials_vault_ref and self.secret_store:
                    vault_secret = await self.secret_store.get_secret(partner.credentials_vault_ref)
                    client_key = vault_secret
                    password = ""
        except ValueError:
            async with self.uow_factory() as uow, uow:
                await uow.transactions.update_edi_message_status(trace_id, MessageStatus.FAILED)
                await self._emit_delivery_completed(
                    uow, trace_id, edi_msg.direction, MessageStatus.FAILED
                )
                await uow.commit()
            logger.exception(
                "SFTP delivery terminal failure for trace_id={trace_id}", trace_id=trace_id
            )
            raise
        except Exception:
            logger.exception(
                "SFTP delivery transient failure for trace_id={trace_id}", trace_id=trace_id
            )
            raise

        try:
            await self.sftp_delivery.deliver(
                host=partner.host,
                port=partner.port,
                username=partner.username,
                password=password or "",
                host_key=partner.host_key,
                client_key=client_key,
                remote_path=partner.outbound_remote_path or "/",
                filename=filename,
                payload=raw_payload,
            )
        except Exception as e:
            logger.exception(
                "SFTP delivery HTTP transmission failed for trace_id={trace_id}", trace_id=trace_id
            )
            raise RuntimeError(f"SFTP delivery failed: {e}") from e

        async with self.uow_factory() as uow, uow:
            await uow.transactions.update_edi_message_status(trace_id, MessageStatus.DELIVERED)
            await self._emit_delivery_completed(
                uow, trace_id, edi_msg.direction, MessageStatus.DELIVERED
            )
            await uow.commit()

        logger.info(
            "Delivered trace_id={trace_id} → SFTP {partner_host}",
            trace_id=trace_id,
            partner_host=partner.host,
        )
