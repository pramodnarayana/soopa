import contextlib
import json
import re
import typing

import structlog
from secret_store.ports.secret_store_port import SecretStorePort
from seedwork.domain.exceptions import ErrorCode

from edi.core.pipeline.as2_orchestrator import AS2MessageOrchestrator
from edi.core.pipeline.delivery.base import (
    BaseDeliveryStrategy,
    TerminalDeliveryError,
    TransientDeliveryError,
)
from edi.domain.partner.as2.messages import OutboundAS2Message
from edi.domain.partner.as2.partner import AS2Partner
from edi.domain.partner.as2.partnership import AS2Partnership
from edi.domain.partner.as2.protocol import parse_mdn
from edi.domain.routing.enums import EdiDirection
from edi.domain.transaction.edi_message import EdiMessage
from edi.ports.outbound.as2_delivery_port import AS2DeliveryPort
from edi.ports.outbound.crypto_service_port import CryptoServicePort
from edi.ports.outbound.exceptions import PortConnectionError, PortTimeoutError
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class As2DeliveryStrategy(BaseDeliveryStrategy):
    def __init__(
        self,
        uow_factory: typing.Callable[
            [], contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]
        ],
        as2_delivery: AS2DeliveryPort,
        vault: SecretStorePort | None = None,
        crypto_service: CryptoServicePort | None = None,
    ) -> None:
        super().__init__(uow_factory, vault)
        self.as2_delivery = as2_delivery
        self._as2_orchestrator = AS2MessageOrchestrator(vault=vault, crypto_service=crypto_service)

    async def _process_mdn_response(
        self,
        trace_id: str,
        direction: str,
        as2_msg: OutboundAS2Message,
        status_code: int,
        response_headers: dict[str, str],
        response_body: bytes,
        idempotency_key: str | None = None,
        edi_msg: EdiMessage | None = None,
    ) -> None:
        if not (200 <= status_code < 300):
            logger.error(
                "as2_delivery_http_failed",
                trace_id=trace_id,
                status_code=status_code,
            )
            # Transient error, raise so outbox can retry if applicable
            raise TransientDeliveryError(
                message=f"AS2 Delivery failed with HTTP {status_code}",
                code=ErrorCode.UNKNOWN_TRANSPORT_ERROR,
                details={"status_code": status_code},
            )

        try:
            mdn = parse_mdn(response_headers, response_body)
        except ValueError as e:
            logger.error(
                "as2_mdn_parse_failed",
                trace_id=trace_id,
                error=str(e),
            )
            raise TerminalDeliveryError(
                message=f"AS2 MDN parsing or processing failed: {e}",
                code=ErrorCode.VALIDATION_FAILED,
                details={"error": str(e)},
            ) from e

        disposition = mdn.disposition
        received_mic = mdn.mic

        if edi_msg:
            edi_msg.mdn_mode = "SYNC"
            edi_msg.mdn_response = response_body.decode("utf-8", errors="ignore").replace(
                "\x00", ""
            )
            # Usually the MDN has a Message-ID header too, we could set mdn_id
            edi_msg.mdn_id = response_headers.get("Message-ID") or response_headers.get(
                "message-id"
            )

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
                        logger.error(
                            "as2_mdn_mic_mismatch",
                            trace_id=trace_id,
                            expected_mic=as2_msg.mic,
                            received_mic=received_mic,
                        )

        if is_success:
            logger.info(
                "as2_delivery_succeeded",
                trace_id=trace_id,
                status_code=status_code,
                mic=as2_msg.mic,
            )
            return

        logger.error(
            "as2_mdn_failure",
            trace_id=trace_id,
            disposition=disposition,
            received_mic=received_mic,
            expected_mic=as2_msg.mic,
        )
        raise TerminalDeliveryError(
            message=f"Sync MDN indicates failure: {disposition}",
            code=ErrorCode.VALIDATION_FAILED,
            details={"disposition": disposition},
        )

    async def _fetch_and_map_partners(
        self, tenant_id: str, partner_id: str
    ) -> tuple[str, AS2Partner, AS2Partnership, AS2Partner | None]:
        async with self.uow_factory() as uow, uow:
            partnerships = await uow.as2_partnerships.get_as2_partnerships_by_remote_partner_id(
                tenant_id, partner_id, active=True
            )
            if not partnerships:
                raise TerminalDeliveryError(
                    message=f"No active AS2 partnership found for remote partner {partner_id}.",
                    code=ErrorCode.NOT_FOUND,
                    details={"partner_id": partner_id},
                )

            if len(partnerships) != 1:
                logger.error(
                    "multiple_active_as2_partnerships_found_for_remote_partner",
                    tenant_id=tenant_id,
                    remote_partner_id=partner_id,
                )
                raise TerminalDeliveryError(
                    message=f"Expected exactly 1 active AS2 partnership for remote partner {partner_id}, found {len(partnerships)}.",
                    code=ErrorCode.CONFLICT,
                    details={"partner_id": partner_id, "found": len(partnerships)},
                )

            partnership = partnerships[0]

            remote_partner = await uow.as2_partners.get_as2_partner(
                tenant_id, partnership.remote_partner_id
            )
            if not remote_partner:
                raise TerminalDeliveryError(
                    message="AS2 remote partner not found.", code=ErrorCode.NOT_FOUND
                )

            remote_url: str | None = remote_partner.url
            if not remote_url:
                raise TerminalDeliveryError(
                    message=f"AS2 partner {partner_id} has no remote_url configured.",
                    code=ErrorCode.VALIDATION_FAILED,
                    details={"partner_id": partner_id},
                )

            local_partner_id: str | None = partnership.local_partner_id
            local_partner = (
                await uow.as2_partners.get_as2_partner(tenant_id, local_partner_id)
                if local_partner_id
                else None
            )

        return remote_url, remote_partner, partnership, local_partner

    async def deliver(
        self,
        trace_id: str,
        partner_id: str,
        edi_msg: EdiMessage,
        idempotency_key: str | None = None,
    ) -> None:
        direction = str(edi_msg.direction) if edi_msg.direction else EdiDirection.OUTBOUND.value

        try:
            (
                remote_url,
                remote_dto,
                partnership_dto_mapped,
                local_dto,
            ) = await self._fetch_and_map_partners(edi_msg.tenant_id, partner_id)

            if not edi_msg.edi_data:
                raise TerminalDeliveryError(
                    message="Empty EDI data", code=ErrorCode.INVALID_PAYLOAD
                )
            raw_payload = edi_msg.edi_data.encode("utf-8")

            as2_msg = await self._as2_orchestrator.build(
                raw_payload=raw_payload,
                local_partner=local_dto,
                remote_partner=remote_dto,
                partnership=partnership_dto_mapped,
                idempotency_key=idempotency_key,
            )

            # Populate outbound AS2 metadata on the aggregate
            edi_msg.message_id = as2_msg.headers.get("Message-ID")
            edi_msg.as2_sender_id = as2_msg.headers.get("AS2-From")
            edi_msg.as2_receiver_id = as2_msg.headers.get("AS2-To")
            edi_msg.content_type = as2_msg.headers.get("Content-Type")
            edi_msg.signature_algorithm = partnership_dto_mapped.signature_algorithm
            edi_msg.encryption_algorithm = partnership_dto_mapped.encryption_algorithm
            edi_msg.msg_headers = json.dumps(as2_msg.headers).replace("\x00", "")
            content_disposition = as2_msg.headers.get("Content-Disposition")
            if content_disposition:
                match = re.search(r'filename="([^"]+)"', content_disposition, re.IGNORECASE)
                edi_msg.file_name = match.group(1) if match else content_disposition

        except ValueError as e:
            logger.error(
                "as2_message_build_terminal_failure",
                trace_id=trace_id,
                partner_id=partner_id,
                error=str(e),
            )
            raise TerminalDeliveryError(
                message=f"AS2 message build error: {e}",
                code=ErrorCode.VALIDATION_FAILED,
                details={"error": str(e)},
            ) from e

        try:
            status_code, response_headers, response_body = await self.as2_delivery.deliver(
                url=remote_url,
                body=as2_msg.body,
                headers=as2_msg.headers,
            )
        except (PortConnectionError, PortTimeoutError) as e:
            logger.error(
                "as2_http_transmission_failed",
                trace_id=trace_id,
                remote_url=remote_url,
                error=str(e),
            )
            error_code = (
                ErrorCode.CONNECTION_TIMEOUT
                if isinstance(e, PortTimeoutError)
                else ErrorCode.CONNECTION_REFUSED
            )
            raise TransientDeliveryError(
                message=f"AS2 transmission error: {e}",
                code=error_code,
                details={"error": str(e), "remote_url": remote_url},
            ) from e

        await self._process_mdn_response(
            trace_id,
            direction,
            as2_msg,
            status_code,
            response_headers,
            response_body,
            idempotency_key,
            edi_msg,
        )
