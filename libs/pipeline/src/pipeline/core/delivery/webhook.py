import json
import logging

from domain.models import EdiMessageDomainModel
from domain.status import MessageStatus
from pipeline.core.delivery.base import BaseDeliveryStrategy
from pipeline.ports.http import HttpDeliveryPort
from pipeline.ports.repository import RepositoryPort
from pipeline.ports.vault import VaultPort

logger = logging.getLogger(__name__)


class WebhookDeliveryStrategy(BaseDeliveryStrategy):
    def __init__(
        self,
        repository: RepositoryPort,
        http_delivery: HttpDeliveryPort,
        vault: VaultPort | None = None,
    ) -> None:
        super().__init__(repository, vault)
        self.http_delivery = http_delivery

    async def deliver(self, trace_id: str, partner_id: str, edi_msg: EdiMessageDomainModel) -> None:
        if not await self.repository.claim_api_payload(trace_id):
            logger.warning(f"Could not claim trace_id={trace_id} (already claimed or terminal).")
            return

        api_payload = await self.repository.get_api_payload(trace_id)
        if not api_payload:
            raise ValueError(f"No API Payload found for webhook delivery of trace_id={trace_id}")

        partner = await self.repository.get_webhook(partner_id)
        if not partner:
            raise ValueError(f"Webhook partner {partner_id} not found.")

        try:
            payload_data = api_payload.get("payload")
            if not payload_data:
                raise ValueError(f"ApiGateway payload is empty for trace_id={trace_id}")

            raw_payload = json.dumps(payload_data).encode("utf-8")

            auth_token = None
            if partner.get("auth_header_vault_ref"):
                if not self.vault:
                    raise ValueError(
                        "Vault is not configured but webhook partner requires an auth token."
                    )
                auth_token = await self.vault.get_secret(partner["auth_header_vault_ref"])

            status_code, response_text = await self.http_delivery.deliver(
                url=partner["url"], payload=raw_payload, auth_token=auth_token
            )
        except Exception as e:
            await self.repository.update_api_payload_status(
                trace_id, MessageStatus.FAILED, webhook_url=partner.get("url"), response=str(e)
            )
            await self._emit_delivery_completed(trace_id, edi_msg.direction, MessageStatus.FAILED)
            logger.exception(f"Webhook delivery failed for trace_id={trace_id}")
            return

        if 200 <= status_code < 300:
            await self.repository.update_api_payload_status(
                trace_id,
                MessageStatus.DELIVERED,
                webhook_url=partner.get("url"),
                http_status_code=status_code,
                response=response_text,
            )
            await self._emit_delivery_completed(
                trace_id, edi_msg.direction, MessageStatus.DELIVERED
            )
            logger.info(f"Delivered trace_id={trace_id} → webhook {partner['url']}")
        else:
            await self.repository.update_api_payload_status(
                trace_id,
                MessageStatus.FAILED,
                webhook_url=partner.get("url"),
                http_status_code=status_code,
                response=response_text,
            )
            await self._emit_delivery_completed(trace_id, edi_msg.direction, MessageStatus.FAILED)
            logger.error(f"Webhook delivery failed for trace_id={trace_id}. HTTP {status_code}")
