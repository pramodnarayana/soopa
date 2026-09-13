import json

import structlog
from secret_store.ports.secret_store_port import SecretStorePort
from seedwork.constants import SystemIdPrefix
from seedwork.utils import generate_id

from edi.core.pipeline.delivery.base import BaseDeliveryStrategy
from edi.domain.enums import MessageStatus
from edi.domain.models.transactions import EdiMessageDomainModel
from edi.ports.outbound.http_delivery_port import HttpDeliveryPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

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
        if not await self.uow.transactions.claim_api_payload(trace_id):
            logger.warning(
                "Could not claim trace_id={trace_id} (already claimed or terminal).",
                trace_id=trace_id,
            )
            return

        api_payload = await self.uow.transactions.get_api_payload(trace_id)
        if not api_payload:
            raise ValueError(f"No API Payload found for webhook delivery of trace_id={trace_id}")

        partner = await self.uow.webhooks.get_webhook(edi_msg.tenant_id, partner_id)
        if not partner:
            raise ValueError(f"Webhook partner {partner_id} not found.")

        try:
            payload_data = api_payload.get("payload")
            if not payload_data:
                raise ValueError(f"ApiGateway payload is empty for trace_id={trace_id}")

            raw_payload = json.dumps(payload_data).encode("utf-8")

            auth_token = None
            if partner.auth_header_vault_ref:
                if not self.secret_store:
                    raise ValueError(
                        "Secret store is not configured but webhook partner requires an auth token."
                    )
                auth_token = await self.secret_store.get_secret(partner.auth_header_vault_ref)

            # Pass idempotency_key down to the http_delivery if it supports it, or add it to headers manually
            status_code, response_text = await self.http_delivery.deliver(
                url=partner.url,
                payload=raw_payload,
                auth_token=auth_token,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.GENERIC),
            )
        except Exception as e:
            await self.uow.transactions.update_api_payload_status(trace_id, MessageStatus.FAILED)
            await self._emit_delivery_completed(trace_id, edi_msg.direction, MessageStatus.FAILED)
            await self.uow.commit()
            logger.exception("Webhook delivery failed for trace_id={trace_id}", trace_id=trace_id)
            raise RuntimeError(f"Webhook delivery failed: {e}") from e

        if 200 <= status_code < 300:
            await self.uow.transactions.update_api_payload_status(trace_id, MessageStatus.DELIVERED)
            await self._emit_delivery_completed(
                trace_id, edi_msg.direction, MessageStatus.DELIVERED
            )
            logger.info(
                "Delivered trace_id={trace_id} → webhook {partner_url}",
                trace_id=trace_id,
                partner_url=partner.url,
            )
        else:
            await self.uow.transactions.update_api_payload_status(trace_id, MessageStatus.FAILED)
            await self._emit_delivery_completed(trace_id, edi_msg.direction, MessageStatus.FAILED)
            await self.uow.commit()
            logger.error(
                "Webhook delivery failed for trace_id={trace_id}. HTTP {status_code}",
                trace_id=trace_id,
                status_code=status_code,
            )
            raise RuntimeError(f"Webhook delivery failed with HTTP {status_code}: {response_text}")
