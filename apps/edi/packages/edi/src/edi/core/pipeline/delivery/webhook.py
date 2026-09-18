import contextlib
import json
import typing

import structlog
from secret_store.ports.secret_store_port import SecretStorePort
from seedwork.id_registry import SystemIdPrefix
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
        uow_factory: typing.Callable[
            [], contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]
        ],
        http_delivery: HttpDeliveryPort,
        vault: SecretStorePort | None = None,
    ) -> None:
        super().__init__(uow_factory, vault)
        self.http_delivery = http_delivery

    async def deliver(
        self,
        trace_id: str,
        partner_id: str,
        edi_msg: EdiMessageDomainModel,
        idempotency_key: str | None = None,
    ) -> None:
        try:
            async with self.uow_factory() as uow, uow:
                api_payload = await uow.transactions.get_api_payload(trace_id)
                if not api_payload:
                    raise ValueError(
                        f"No API Payload found for webhook delivery of trace_id={trace_id}"
                    )

                partner = await uow.webhooks.get_webhook(edi_msg.tenant_id, partner_id)
                if not partner:
                    raise ValueError(f"Webhook partner {partner_id} not found.")

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
        except ValueError:
            async with self.uow_factory() as uow, uow:
                await uow.transactions.update_api_payload_status(
                    trace_id=trace_id,
                    status=MessageStatus.FAILED,
                    webhook_url=partner.url if "partner" in locals() and partner else None,
                )
                await self._emit_delivery_completed(
                    uow, trace_id, edi_msg.direction, MessageStatus.FAILED
                )
                await uow.commit()
            logger.exception(
                "Webhook delivery terminal failure for trace_id={trace_id}", trace_id=trace_id
            )
            raise
        except Exception:
            logger.exception(
                "Webhook delivery transient failure for trace_id={trace_id}", trace_id=trace_id
            )
            raise

        try:
            # Pass idempotency_key down to the http_delivery if it supports it, or add it to headers manually
            status_code, response_text = await self.http_delivery.deliver(
                url=partner.url,
                payload=raw_payload,
                auth_token=auth_token,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.GENERIC),
            )
        except Exception as e:
            logger.exception(
                "Webhook delivery HTTP transmission failed for trace_id={trace_id}",
                trace_id=trace_id,
            )
            raise RuntimeError(f"Webhook delivery failed: {e}") from e

        if 200 <= status_code < 300:
            async with self.uow_factory() as uow, uow:
                await uow.transactions.update_api_payload_status(
                    trace_id=trace_id,
                    status=MessageStatus.DELIVERED,
                    webhook_url=partner.url,
                    http_status_code=status_code,
                    response=response_text[:4000] if response_text else None,  # Cap response size
                )
                await self._emit_delivery_completed(
                    uow, trace_id, edi_msg.direction, MessageStatus.DELIVERED
                )
                await uow.commit()
            logger.info(
                "Delivered trace_id={trace_id} → webhook {partner_url}",
                trace_id=trace_id,
                partner_url=partner.url,
            )
        else:
            async with self.uow_factory() as uow, uow:
                await uow.transactions.update_api_payload_status(
                    trace_id=trace_id,
                    status=MessageStatus.FAILED,
                    webhook_url=partner.url,
                    http_status_code=status_code,
                    response=response_text[:4000] if response_text else None,
                )
                await self._emit_delivery_completed(
                    uow, trace_id, edi_msg.direction, MessageStatus.FAILED
                )
                await uow.commit()
            logger.error(
                "Webhook delivery failed for trace_id={trace_id}. HTTP {status_code}",
                trace_id=trace_id,
                status_code=status_code,
            )
            # Transient error, raise so outbox can retry if applicable
            raise RuntimeError(f"Webhook delivery failed with HTTP {status_code}: {response_text}")
