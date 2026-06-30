import logging
from typing import Any

from pipeline.ports.http import HttpDeliveryPort
from pipeline.ports.repository import RepositoryPort
from pipeline.ports.sftp import SftpDeliveryPort
from pipeline.ports.storage import StoragePort
from pipeline.ports.vault import VaultPort

logger = logging.getLogger(__name__)


class DeliveryService:
    """
    Pure domain service for orchestrating delivery of payloads (JSON or EDI).
    Follows Hexagonal Architecture and performs dynamic Envelope Routing.
    """

    def __init__(
        self,
        storage: StoragePort,
        repository: RepositoryPort,
        http_delivery: HttpDeliveryPort,
        sftp_delivery: SftpDeliveryPort,
        vault: VaultPort | None = None,
    ) -> None:
        self.storage = storage
        self.repository = repository
        self.http_delivery = http_delivery
        self.sftp_delivery = sftp_delivery
        self.vault = vault

    async def deliver(self, trace_id: str) -> None:
        """
        Dynamically looks up the route using the ISA envelope and delivers
        the payload to the configured trading partner.
        """
        logger.info(f"Starting delivery pipeline for trace_id={trace_id}")

        edi_msg = await self.repository.get_edi_message(trace_id)
        if not edi_msg:
            raise ValueError(f"No EDI Message found for trace_id={trace_id}")

        direction = edi_msg["direction"]
        sender_id = edi_msg.get("sender_id")
        receiver_id = edi_msg.get("receiver_id")
        transaction_type = edi_msg.get("transaction_type", "*")

        if not sender_id or not receiver_id:
            raise ValueError(f"EDI Message {trace_id} is missing sender/receiver IDs for routing.")

        # 1. Lookup Route
        route = await self.repository.get_route(direction, sender_id, receiver_id, transaction_type)
        if not route:
            logger.error(f"No {direction} route found for {sender_id}->{receiver_id}")
            raise ValueError(f"No route found for {direction} {sender_id}->{receiver_id}")

        # 2. Execute Delivery based on configured partner
        if route.get("webhook_partner_id"):
            await self._deliver_webhook(trace_id, route["webhook_partner_id"])
        elif route.get("sftp_partner_id"):
            await self._deliver_sftp(trace_id, route["sftp_partner_id"], edi_msg)
        elif route.get("as2_partner_id"):
            await self._deliver_as2(trace_id, route["as2_partner_id"], edi_msg)
        else:
            raise ValueError(
                f"Route {route['route_id']} is not configured with any destination partner."
            )

    async def _deliver_webhook(self, trace_id: str, partner_id: str) -> None:
        # Webhook delivery expects the JSON translated ApiPayload
        if not await self.repository.claim_api_payload(trace_id):
            logger.warning(f"Could not claim trace_id={trace_id} (already claimed or terminal).")
            return

        api_payload = await self.repository.get_api_payload(trace_id)
        if not api_payload:
            raise ValueError(f"No API Payload found for webhook delivery of trace_id={trace_id}")

        partner = await self.repository.get_webhook_partner(partner_id)
        if not partner:
            raise ValueError(f"Webhook partner {partner_id} not found.")

        try:
            raw_payload = await self.storage.download(api_payload["s3_key"])

            auth_token = None
            if partner.get("auth_header_vault_ref") and self.vault:
                auth_token = await self.vault.get_secret(partner["auth_header_vault_ref"])

            status_code = await self.http_delivery.deliver(
                url=partner["url"], payload=raw_payload, auth_token=auth_token
            )
        except Exception:
            await self.repository.update_api_payload_status(trace_id, "FAILED")
            logger.exception(f"Delivery failed for trace_id={trace_id}")
            return

        if 200 <= status_code < 300:
            await self.repository.update_api_payload_status(trace_id, "DELIVERED")
            logger.info(f"Successfully delivered trace_id={trace_id} to webhook {partner['url']}")
        else:
            await self.repository.update_api_payload_status(trace_id, "FAILED")
            logger.error(f"Failed to deliver trace_id={trace_id}. HTTP Status: {status_code}")
            return

    async def _deliver_sftp(self, trace_id: str, partner_id: str, edi_msg: dict[str, Any]) -> None:
        if not await self.repository.claim_edi_message(trace_id):
            logger.warning(f"Could not claim trace_id={trace_id} (already claimed or terminal).")
            return

        partner = await self.repository.get_sftp_partner(partner_id)
        if not partner:
            raise ValueError(f"SFTP partner {partner_id} not found.")

        # We deliver the EDI payload directly for SFTP
        try:
            raw_payload = await self.storage.download(edi_msg["s3_key"])
            # Generate a filename
            filename = f"{trace_id}.edi"

            password = partner["credentials_vault_ref"]
            if password and self.vault:
                password = await self.vault.get_secret(password)

            await self.sftp_delivery.deliver(
                host=partner["host"],
                port=partner["port"],
                username=partner["username"],
                password=password,
                host_key=None,
                remote_path=partner["remote_path"],
                filename=filename,
                payload=raw_payload,
            )
            await self.repository.update_edi_message_status(trace_id, "DELIVERED")
            logger.info(f"Successfully delivered trace_id={trace_id} to SFTP {partner['host']}")
        except Exception:
            await self.repository.update_edi_message_status(trace_id, "FAILED")
            logger.exception(f"SFTP delivery failed for trace_id={trace_id}")
            return

    async def _deliver_as2(self, trace_id: str, partner_id: str, edi_msg: dict[str, Any]) -> None:
        partner = await self.repository.get_as2_partner(partner_id)
        if not partner:
            raise ValueError(f"AS2 partner {partner_id} not found.")

        raise NotImplementedError("AS2 dispatch via pyas2/Mendelson is not yet implemented.")
        logger.info(f"Mock AS2 delivery successful for trace_id={trace_id} to {partner['as2_id']}")
