from typing import Any

import structlog
from domain.models import EdiMessageDomainModel
from domain.status import MessageStatus

from pipeline.core.as2_orchestrator import AS2MessageOrchestrator
from pipeline.core.delivery.base import BaseDeliveryStrategy
from pipeline.ports.as2 import AS2DeliveryPort
from pipeline.ports.repository import RepositoryPort
from pipeline.ports.vault import VaultPort

logger = structlog.get_logger(__name__)


class As2DeliveryStrategy(BaseDeliveryStrategy):
    def __init__(
        self,
        repository: RepositoryPort,
        as2_delivery: AS2DeliveryPort,
        vault: VaultPort | None = None,
    ) -> None:
        super().__init__(repository, vault)
        self.as2_delivery = as2_delivery
        self._as2_orchestrator = AS2MessageOrchestrator(vault=vault)

    async def _process_mdn_response(
        self,
        trace_id: str,
        direction: str,
        as2_msg: Any,
        status_code: int,
        response_headers: dict[str, str],
        response_body: bytes,
    ) -> None:
        if not (200 <= status_code < 300):
            await self.repository.update_edi_message_status(trace_id, MessageStatus.FAILED)
            await self._emit_delivery_completed(trace_id, direction, MessageStatus.FAILED)
            logger.error(
                "AS2 Delivery failed for trace_id={trace_id}. "
                "HTTP status: {status_code}, body: {response_body!r}"
            )
            return

        from as2_core import parse_mdn

        try:
            mdn = parse_mdn(response_headers, response_body)
            disposition = mdn.disposition
            received_mic = mdn.mic

            is_success = False
            if disposition:
                disp_parts = disposition.split(";", 1)
                if len(disp_parts) == 2:
                    status_part = disp_parts[1].strip().lower()
                    if (
                        status_part.startswith("processed")
                        and "error" not in status_part
                        and "failed" not in status_part
                    ):
                        is_success = True
                        if as2_msg.mic and (
                            not received_mic
                            or as2_msg.mic.replace(" ", "") != received_mic.replace(" ", "")
                        ):
                            is_success = False
                            logger.warning(
                                "MDN MIC mismatch for trace_id={trace_id}. "
                                "Expected {as2_msg.mic}, got {received_mic}"
                            )

            if is_success:
                await self.repository.update_edi_message_status(trace_id, MessageStatus.DELIVERED)
                await self._emit_delivery_completed(trace_id, direction, MessageStatus.DELIVERED)
                logger.info(
                    "Delivered trace_id={trace_id} (HTTP {status_code}). MIC={as2_msg.mic}",
                    trace_id=trace_id,
                    status_code=status_code,
                    as2_msg_mic=as2_msg.mic,
                )
            else:
                await self.repository.update_edi_message_status(trace_id, MessageStatus.FAILED)
                await self._emit_delivery_completed(trace_id, direction, MessageStatus.FAILED)
                logger.error(
                    "Sync MDN indicates failure for trace_id={trace_id}. "
                    "Disposition: {disposition!r}, Received-MIC: {received_mic!r}, Expected-MIC: {as2_msg.mic!r}"
                )
        except Exception:
            await self.repository.update_edi_message_status(trace_id, MessageStatus.FAILED)
            await self._emit_delivery_completed(trace_id, direction, MessageStatus.FAILED)
            logger.exception(
                "AS2 MDN parsing or processing failed for trace_id={trace_id}", trace_id=trace_id
            )

    async def deliver(
        self,
        trace_id: str,
        partner_id: str,
        edi_msg: EdiMessageDomainModel,
        idempotency_key: str | None = None,
    ) -> None:
        if not await self.repository.claim_edi_message(trace_id):
            logger.warning(
                "Could not claim trace_id={trace_id} (already claimed or terminal).",
                trace_id=trace_id,
            )
            return

        try:
            remote_partner = await self.repository.get_as2_partner(partner_id)
            if not remote_partner:
                raise ValueError("AS2 partner {partner_id} not found.")

            remote_url: str | None = remote_partner.get("remote_url")
            if not remote_url:
                raise ValueError("AS2 partner {partner_id} has no remote_url configured.")

            local_partner_id: str | None = remote_partner.get("local_partner_id")
            local_partner = (
                await self.repository.get_local_as2_partner(local_partner_id)
                if local_partner_id
                else None
            )

            if not edi_msg.edi_data:
                raise ValueError("Empty EDI data")
            raw_payload = edi_msg.edi_data.encode("utf-8")

            as2_msg = await self._as2_orchestrator.build(
                raw_payload=raw_payload,
                local_partner=local_partner,
                remote_partner=remote_partner,
                idempotency_key=idempotency_key,
            )
        except Exception as e:
            await self.repository.update_edi_message_status(trace_id, MessageStatus.FAILED)
            await self._emit_delivery_completed(trace_id, edi_msg.direction, MessageStatus.FAILED)
            logger.exception(
                "AS2 Delivery Adapter is misconfigured or failed to build for trace_id={trace_id}",
                trace_id=trace_id,
            )
            raise RuntimeError(
                "AS2 Delivery Adapter failed to build for trace_id={trace_id}"
            ) from e

        try:
            status_code, response_headers, response_body = await self.as2_delivery.deliver(
                url=remote_url,
                body=as2_msg.body,
                headers=as2_msg.headers,
            )
        except RuntimeError as e:
            await self.repository.update_edi_message_status(trace_id, MessageStatus.FAILED)
            await self._emit_delivery_completed(trace_id, edi_msg.direction, MessageStatus.FAILED)
            logger.exception(
                "AS2 Delivery Adapter is misconfigured for trace_id={trace_id}", trace_id=trace_id
            )
            raise RuntimeError(
                "AS2 Delivery Adapter is misconfigured for trace_id={trace_id}"
            ) from e
        except Exception as e:
            await self.repository.update_edi_message_status(trace_id, MessageStatus.FAILED)
            await self._emit_delivery_completed(trace_id, edi_msg.direction, MessageStatus.FAILED)
            logger.exception(
                "AS2 HTTP transmission failed for trace_id={trace_id}", trace_id=trace_id
            )
            raise RuntimeError("AS2 HTTP transmission failed for trace_id={trace_id}") from e

        await self._process_mdn_response(
            trace_id, edi_msg.direction, as2_msg, status_code, response_headers, response_body
        )
