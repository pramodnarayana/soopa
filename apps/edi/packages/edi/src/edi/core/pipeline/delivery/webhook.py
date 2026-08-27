import json

import structlog
from secret_store.ports.secret_store_port import SecretStorePort

from edi.core.pipeline.delivery.base import BaseDeliveryStrategy
from edi.domain.models import EdiMessageDomainModel
from edi.domain.status import MessageStatus
from edi.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort
from edi.ports.outbound.http_delivery_port import HttpDeliveryPort

logger = structlog.get_logger(__name__)


class WebhookDeliveryStrategy(BaseDeliveryStrategy):
    def __init__(
        self,
        uow: DataPlaneUnitOfWorkPort,
        http_delivery: HttpDeliveryPort,
        vault: SecretStorePort | None = None,
    ) -> None:
        super().__init__(uow, vault)
        self.http_delivery = http_delivery

    async def deliver(
        self,
        trace_id: str,
        partner_id: str,
        edi_msg: EdiMessageDomainModel,
        idempotency_key: str | None = None,
    ) -> None:
        if not await self.uow.repository.claim_api_payload(trace_id):
            logger.warning(
                "Could not claim trace_id={trace_id} (already claimed or terminal).",
                trace_id=trace_id,
            )
            return

        api_payload = await self.uow.repository.get_api_payload(trace_id)
        if not api_payload:
            raise ValueError(f"No API Payload found for webhook delivery of trace_id={trace_id}")

        partner = await self.uow.repository.get_webhook(partner_id)
        if not partner:
            raise ValueError(f"Webhook partner {partner_id} not found.")

        try:
            payload_data = api_payload.get("payload")
            if not payload_data:
                raise ValueError(f"ApiGateway payload is empty for trace_id={trace_id}")

            raw_payload = json.dumps(payload_data).encode("utf-8")

            auth_token = None
            if partner.get("auth_header_vault_ref"):
                if not self.secret_store:
                    raise ValueError(
                        "Secret store is not configured but webhook partner requires an auth token."
                    )
                auth_token = await self.secret_store.get_secret(partner["auth_header_vault_ref"])

            # Pass idempotency_key down to the http_delivery if it supports it, or add it to headers manually
            status_code, response_text = await self.http_delivery.deliver(
                url=partner["url"],
                payload=raw_payload,
                auth_token=auth_token,
                idempotency_key=idempotency_key,
            )
        except Exception as e:
            await self.uow.repository.update_api_payload_status(
                trace_id, MessageStatus.FAILED, webhook_url=partner.get("url"), response=str(e)
            )
            await self._emit_delivery_completed(trace_id, edi_msg.direction, MessageStatus.FAILED)
            logger.exception("Webhook delivery failed for trace_id={trace_id}", trace_id=trace_id)
            return

        if 200 <= status_code < 300:
            await self.uow.repository.update_api_payload_status(
                trace_id,
                MessageStatus.DELIVERED,
                webhook_url=partner.get("url"),
                http_status_code=status_code,
                response=response_text,
            )
            await self._emit_delivery_completed(
                trace_id, edi_msg.direction, MessageStatus.DELIVERED
            )
            logger.info(
                "Delivered trace_id={trace_id} → webhook {partner['url']}",
                trace_id=trace_id,
                partnerurl=partner["url"],
            )
        else:
            await self.uow.repository.update_api_payload_status(
                trace_id,
                MessageStatus.FAILED,
                webhook_url=partner.get("url"),
                http_status_code=status_code,
                response=response_text,
            )
            await self._emit_delivery_completed(trace_id, edi_msg.direction, MessageStatus.FAILED)
            logger.error(
                "Webhook delivery failed for trace_id={trace_id}. HTTP {status_code}",
                trace_id=trace_id,
                status_code=status_code,
            )
