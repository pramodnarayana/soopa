import structlog
from secret_store.ports.secret_store_port import SecretStorePort

from edi.core.pipeline.delivery.base import BaseDeliveryStrategy
from edi.domain.models.transactions import EdiMessageDomainModel
from edi.domain.status import MessageStatus
from edi.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort
from edi.ports.outbound.sftp_delivery_port import SftpDeliveryPort

logger = structlog.get_logger(__name__)


class SftpDeliveryStrategy(BaseDeliveryStrategy):
    def __init__(
        self,
        uow: DataPlaneUnitOfWorkPort,
        sftp_delivery: SftpDeliveryPort,
        vault: SecretStorePort | None = None,
    ) -> None:
        super().__init__(uow, vault)
        self.sftp_delivery = sftp_delivery

    async def deliver(
        self,
        trace_id: str,
        partner_id: str,
        edi_msg: EdiMessageDomainModel,
        idempotency_key: str | None = None,
    ) -> None:
        if not await self.uow.repository.claim_edi_message(trace_id):
            logger.warning(
                "Could not claim trace_id={trace_id} (already claimed or terminal).",
                trace_id=trace_id,
            )
            return

        try:
            partner = await self.uow.repository.get_sftp_partner(partner_id)
            if not partner:
                raise ValueError(f"SFTP partner {partner_id} not found.")
            if not edi_msg.edi_data:
                raise ValueError("Empty EDI data")
            raw_payload = edi_msg.edi_data.encode("utf-8")
            filename = f"{trace_id}.edi"

            password: str | None = partner.password
            client_key: str | None = None

            if not password and partner.credentials_vault_ref and self.secret_store:
                vault_secret = await self.secret_store.get_secret(partner.credentials_vault_ref)
                client_key = vault_secret
                password = ""

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
            await self.uow.repository.update_edi_message_status(trace_id, MessageStatus.DELIVERED)
            await self._emit_delivery_completed(
                trace_id, edi_msg.direction, MessageStatus.DELIVERED
            )
            logger.info(
                "Delivered trace_id={trace_id} → SFTP {partner_host}",
                trace_id=trace_id,
                partner_host=partner.host,
            )
        except Exception as e:
            await self.uow.repository.update_edi_message_status(trace_id, MessageStatus.FAILED)
            await self._emit_delivery_completed(trace_id, edi_msg.direction, MessageStatus.FAILED)
            await self.uow.commit()
            logger.exception("SFTP delivery failed for trace_id={trace_id}", trace_id=trace_id)
            raise RuntimeError(f"SFTP delivery failed: {e}") from e
