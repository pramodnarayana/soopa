import contextlib
import json
from collections.abc import Callable

import structlog
from secret_store.ports.secret_store_port import SecretStorePort

from edi.core.pipeline.delivery.base import (
    BaseDeliveryStrategy,
    TerminalDeliveryError,
    TransientDeliveryError,
)
from edi.core.pipeline.models import EdiWebhookPayload
from edi.domain.enums import EdiDirection, MessageStatus
from edi.domain.models.transactions import EdiMessageDomainModel
from edi.domain.types import JsonDict
from edi.ports.outbound.api_gateway_repository import CreateApiGatewayCommand
from edi.ports.outbound.http_delivery_port import HttpDeliveryPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class WebhookDeliveryStrategy(BaseDeliveryStrategy):
    def __init__(
        self,
        uow_factory: Callable[[], contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]],
        http_delivery: HttpDeliveryPort,
        vault: SecretStorePort | None = None,
    ) -> None:
        super().__init__(uow_factory, vault)
        self.http_delivery = http_delivery

    async def _build_payload(
        self,
        trace_id: str,
        partner_id: str,
        edi_msg: EdiMessageDomainModel,
        uow: DataPlaneUnitOfWorkPort,
    ) -> tuple[str, EdiWebhookPayload, str | None, str]:
        partner = await uow.webhooks.get_webhook(edi_msg.tenant_id, partner_id)
        if not partner:
            raise TerminalDeliveryError(f"Webhook partner {partner_id} not found.")

        edi_jsons = await uow.transactions.get_edi_jsons_by_trace_id(trace_id, edi_msg.tenant_id)
        if not edi_jsons:
            raise TerminalDeliveryError(
                f"No EDI JSONs found for webhook delivery of trace_id={trace_id}"
            )

        standard: str = edi_jsons[0].standard or "Unknown"
        partner_id_from_json = edi_jsons[0].trading_partner_id if edi_jsons else None

        direction_val = edi_msg.direction.value if edi_msg.direction else EdiDirection.INBOUND.value

        # Collect all non-None JSON payloads. j.payload is JsonValue (no Any needed).
        transactions: list[JsonDict] = []
        for j in edi_jsons:
            if isinstance(j.payload, dict):
                transactions.append(j.payload)

        envelope = EdiWebhookPayload.build(
            trace_id=trace_id,
            direction=direction_val,
            sender_id=edi_msg.sender_id,
            receiver_id=edi_msg.receiver_id,
            trading_partner_id=edi_msg.trading_partner_id or partner_id_from_json,
            format_standard=standard,
            transactions=transactions,
        )
        return partner.url, envelope, partner.auth_header_vault_ref, standard

    async def _get_auth_token(self, auth_header_vault_ref: str | None) -> str | None:
        if not auth_header_vault_ref:
            return None
        if not self.secret_store:
            raise TerminalDeliveryError(
                "Secret store is not configured but webhook partner requires an auth token."
            )
        return await self.secret_store.get_secret(auth_header_vault_ref)

    async def _record_api_gateway(
        self,
        trace_id: str,
        edi_msg: EdiMessageDomainModel,
        envelope: EdiWebhookPayload,
        partner_url: str,
        status_code: int | None,
        response_text: str | None,
        error_msg: str | None,
        standard: str,
    ) -> None:
        async with self.uow_factory() as uow, uow:
            final_status = MessageStatus.FAILED
            if status_code is not None and 200 <= status_code < 300:
                final_status = MessageStatus.DELIVERED

            direction = edi_msg.direction if edi_msg.direction else EdiDirection.INBOUND

            await uow.api_gateway_transactions.create_api_gateway(
                CreateApiGatewayCommand(
                    trace_id=trace_id,
                    tenant_id=edi_msg.tenant_id,
                    direction=direction,
                    payload=envelope.model_dump(),
                    status=final_status,
                    transaction_type=standard,
                    webhook_url=partner_url,
                    http_status_code=status_code,
                    response=response_text or error_msg,
                )
            )
            await uow.commit()

    async def deliver(
        self,
        trace_id: str,
        partner_id: str,
        edi_msg: EdiMessageDomainModel,
        idempotency_key: str | None = None,
    ) -> None:
        try:
            async with self.uow_factory() as uow, uow:
                partner_url, envelope, auth_vault_ref, standard = await self._build_payload(
                    trace_id, partner_id, edi_msg, uow
                )

            raw_payload = json.dumps(envelope.model_dump()).encode("utf-8")
            auth_token = await self._get_auth_token(auth_vault_ref)
        except TerminalDeliveryError:
            raise
        except Exception:
            logger.exception(
                "Webhook delivery transient failure for trace_id={trace_id}", trace_id=trace_id
            )
            raise

        status_code = None
        response_text = None
        error_msg = None
        try:
            status_code, response_text = await self.http_delivery.deliver(
                url=partner_url,
                payload=raw_payload,
                auth_token=auth_token,
                idempotency_key=idempotency_key,
            )
        except ValueError as e:
            logger.exception(
                "Webhook delivery configuration error for trace_id={trace_id}",
                trace_id=trace_id,
            )
            error_msg = str(e)
        except TransientDeliveryError:
            logger.exception(
                "Webhook delivery transient transport error for trace_id={trace_id}",
                trace_id=trace_id,
            )
            raise
        except TerminalDeliveryError as e:
            logger.exception(
                "Webhook delivery terminal error for trace_id={trace_id}",
                trace_id=trace_id,
            )
            error_msg = str(e)

        # Re-raise any other unexpected exception instead of converting to TerminalDeliveryError
        # (This is implicitly handled by not having a generic `except Exception` here)

        await self._record_api_gateway(
            trace_id,
            edi_msg,
            envelope,
            partner_url,
            status_code,
            response_text,
            error_msg,
            standard,
        )

        if status_code is not None and (status_code in (429, 529) or 500 <= status_code < 600):
            logger.warning(
                "Webhook delivery received transient HTTP {status_code} for trace_id={trace_id}",
                status_code=status_code,
                trace_id=trace_id,
            )
            raise TransientDeliveryError(
                f"Webhook delivery received transient HTTP {status_code}: {response_text}"
            )

        if error_msg:
            raise TerminalDeliveryError(f"Webhook delivery failed: {error_msg}")
        elif status_code is None or not (200 <= status_code < 300):
            logger.error(
                "Webhook delivery failed for trace_id={trace_id}. HTTP {status_code}",
                trace_id=trace_id,
                status_code=status_code,
            )
            raise TerminalDeliveryError(
                f"Webhook delivery failed with HTTP {status_code}: {response_text}"
            )

        logger.info(
            "Delivered trace_id={trace_id} → webhook {partner_url}",
            trace_id=trace_id,
            partner_url=partner_url,
        )
