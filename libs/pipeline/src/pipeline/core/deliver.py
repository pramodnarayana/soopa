"""
Delivery Service — orchestrates the final-mile delivery of EDI and JSON payloads.

Design decisions:
  - OCP: Uses a handler registry dict instead of an if/elif chain.
    Adding a new protocol (FTP, VAN) requires only adding a new entry to
    `_HANDLER_KEYS` and a new `_deliver_*` method — no modification of existing logic.
  - SRP: AS2 crypto preparation is delegated to AS2MessageOrchestrator.
  - DIP: Depends only on Port abstractions, never on concrete adapters.
  - Fail-fast: `as2_delivery` is required (not Optional). Use NullAS2DeliveryAdapter
    for worker deployments that don't need AS2 delivery.
"""

import logging
from typing import Any

from pipeline.core.as2_orchestrator import AS2MessageOrchestrator
from pipeline.ports.as2 import AS2DeliveryPort
from pipeline.ports.http import HttpDeliveryPort
from pipeline.ports.repository import RepositoryPort
from pipeline.ports.sftp import SftpDeliveryPort
from pipeline.ports.storage import StoragePort
from pipeline.ports.vault import VaultPort

logger = logging.getLogger(__name__)

# ── Handler Registry ──────────────────────────────────────────────────────────
# Maps route field name → method name on DeliveryService.
# OCP: Open for extension (add a key + method), closed for modification
# (existing entries are never touched).
_HANDLER_KEYS: list[tuple[str, str]] = [
    ("webhook_partner_id", "_deliver_webhook"),
    ("sftp_partner_id", "_deliver_sftp"),
    ("as2_partner_id", "_deliver_as2"),
]


class DeliveryService:
    """
    Orchestrates final-mile delivery of EDI and API payloads.
    Routes messages to the correct delivery handler based on the route config.
    """

    def __init__(
        self,
        storage: StoragePort,
        repository: RepositoryPort,
        http_delivery: HttpDeliveryPort,
        sftp_delivery: SftpDeliveryPort,
        as2_delivery: AS2DeliveryPort,
        vault: VaultPort | None = None,
    ) -> None:
        self.storage = storage
        self.repository = repository
        self.http_delivery = http_delivery
        self.sftp_delivery = sftp_delivery
        self.as2_delivery = as2_delivery
        self.vault = vault
        self._as2_orchestrator = AS2MessageOrchestrator(vault=vault)

    async def deliver(self, trace_id: str) -> None:
        """
        Looks up the route for the given trace_id and dispatches to the
        correct delivery handler via the handler registry.
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

        route = await self.repository.get_route(direction, sender_id, receiver_id, transaction_type)
        if not route:
            logger.error(f"No {direction} route found for {sender_id}->{receiver_id}")
            raise ValueError(f"No route found for {direction} {sender_id}->{receiver_id}")

        # ── Dispatch via registry (OCP) ───────────────────────────────────────
        for route_key, handler_name in _HANDLER_KEYS:
            partner_id = route.get(route_key)
            if partner_id:
                handler = getattr(self, handler_name)
                await handler(trace_id, partner_id, edi_msg)
                return

        raise ValueError(
            f"Route {route['route_id']} is not configured with any destination partner."
        )

    # ── Delivery Handlers ─────────────────────────────────────────────────────

    async def _deliver_webhook(
        self, trace_id: str, partner_id: str, edi_msg: dict[str, Any]
    ) -> None:
        """Delivers the translated JSON payload to a webhook endpoint."""
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
            logger.exception(f"Webhook delivery failed for trace_id={trace_id}")
            return

        if 200 <= status_code < 300:
            await self.repository.update_api_payload_status(trace_id, "DELIVERED")
            logger.info(f"Delivered trace_id={trace_id} → webhook {partner['url']}")
        else:
            await self.repository.update_api_payload_status(trace_id, "FAILED")
            logger.error(f"Webhook delivery failed for trace_id={trace_id}. HTTP {status_code}")

    async def _deliver_sftp(self, trace_id: str, partner_id: str, edi_msg: dict[str, Any]) -> None:
        """Uploads the raw EDI payload to the partner's SFTP server."""
        if not await self.repository.claim_edi_message(trace_id):
            logger.warning(f"Could not claim trace_id={trace_id} (already claimed or terminal).")
            return

        partner = await self.repository.get_sftp_partner(partner_id)
        if not partner:
            raise ValueError(f"SFTP partner {partner_id} not found.")

        try:
            raw_payload = await self.storage.download(edi_msg["s3_key"])
            filename = f"{trace_id}.edi"

            password: str = partner["credentials_vault_ref"]
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
            logger.info(f"Delivered trace_id={trace_id} → SFTP {partner['host']}")
        except Exception:
            await self.repository.update_edi_message_status(trace_id, "FAILED")
            logger.exception(f"SFTP delivery failed for trace_id={trace_id}")

    async def _deliver_as2(self, trace_id: str, partner_id: str, edi_msg: dict[str, Any]) -> None:
        """Transmits the EDI payload via AS2 (RFC 4130)."""
        if not await self.repository.claim_edi_message(trace_id):
            logger.warning(f"Could not claim trace_id={trace_id} (already claimed or terminal).")
            return

        remote_partner = await self.repository.get_as2_partner(partner_id)
        if not remote_partner:
            raise ValueError(f"AS2 partner {partner_id} not found.")

        remote_url: str | None = remote_partner.get("remote_url")
        if not remote_url:
            raise ValueError(f"AS2 partner {partner_id} has no remote_url configured.")

        local_partner_id: str | None = remote_partner.get("local_partner_id")
        local_partner = (
            await self.repository.get_local_as2_partner(local_partner_id)
            if local_partner_id
            else None
        )

        raw_payload = await self.storage.download(edi_msg["s3_key"])

        try:
            as2_msg = await self._as2_orchestrator.build(
                raw_payload=raw_payload,
                local_partner=local_partner,
                remote_partner=remote_partner,
            )
        except Exception:
            await self.repository.update_edi_message_status(trace_id, "FAILED")
            logger.exception(f"AS2 message build failed for trace_id={trace_id}")
            return

        try:
            status_code, _response_body = await self.as2_delivery.deliver(
                url=remote_url,
                body=as2_msg.body,
                headers=as2_msg.headers,
            )
        except RuntimeError:
            # Misconfiguration (e.g. NullAS2DeliveryAdapter) — must propagate,
            # not be silently swallowed as a delivery failure.
            raise
        except Exception:
            await self.repository.update_edi_message_status(trace_id, "FAILED")
            logger.exception(f"AS2 HTTP transmission failed for trace_id={trace_id}")
            return

        if 200 <= status_code < 300:
            await self.repository.update_edi_message_status(trace_id, "DELIVERED")
            logger.info(
                f"Delivered trace_id={trace_id} → {remote_url} "
                f"(HTTP {status_code}). MIC={as2_msg.mic}"
            )
            # TODO (Phase 2): Parse _response_body as sync MDN → store in ack_receipts.
        else:
            await self.repository.update_edi_message_status(trace_id, "FAILED")
            logger.error(
                f"AS2 delivery failed for trace_id={trace_id} → {remote_url} (HTTP {status_code})"
            )
