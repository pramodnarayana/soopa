import logging

from domain.models import EdiMessageDomainModel
from domain.status import MessageStatus
from pipeline.core.delivery.base import BaseDeliveryStrategy
from pipeline.ports.repository import RepositoryPort
from pipeline.ports.sftp import SftpDeliveryPort
from pipeline.ports.vault import VaultPort

logger = logging.getLogger(__name__)


class SftpDeliveryStrategy(BaseDeliveryStrategy):
    def __init__(
        self,
        repository: RepositoryPort,
        sftp_delivery: SftpDeliveryPort,
        vault: VaultPort | None = None,
    ) -> None:
        super().__init__(repository, vault)
        self.sftp_delivery = sftp_delivery

    async def deliver(self, trace_id: str, partner_id: str, edi_msg: EdiMessageDomainModel) -> None:
        if not await self.repository.claim_edi_message(trace_id):
            logger.warning(f"Could not claim trace_id={trace_id} (already claimed or terminal).")
            return

        try:
            partner = await self.repository.get_sftp_partner(partner_id)
            if not partner:
                raise ValueError(f"SFTP partner {partner_id} not found.")
            if not edi_msg.edi_data:
                raise ValueError("Empty EDI data")
            raw_payload = edi_msg.edi_data.encode("utf-8")
            filename = f"{trace_id}.edi"

            password: str | None = partner.get("password")
            client_key: str | None = None

            if not password and partner.get("credentials_vault_ref") and self.vault:
                vault_secret = await self.vault.get_secret(partner["credentials_vault_ref"])
                client_key = vault_secret
                password = ""

            await self.sftp_delivery.deliver(
                host=partner["host"],
                port=partner["port"],
                username=partner["username"],
                password=password or "",
                host_key=partner.get("host_key"),
                client_key=client_key,
                remote_path=partner.get("outbound_remote_path") or "/",
                filename=filename,
                payload=raw_payload,
            )
            await self.repository.update_edi_message_status(trace_id, MessageStatus.DELIVERED)
            await self._emit_delivery_completed(
                trace_id, edi_msg.direction, MessageStatus.DELIVERED
            )
            logger.info(f"Delivered trace_id={trace_id} → SFTP {partner['host']}")
        except Exception:
            await self.repository.update_edi_message_status(trace_id, MessageStatus.FAILED)
            await self._emit_delivery_completed(trace_id, edi_msg.direction, MessageStatus.FAILED)
            logger.exception(f"SFTP delivery failed for trace_id={trace_id}")
