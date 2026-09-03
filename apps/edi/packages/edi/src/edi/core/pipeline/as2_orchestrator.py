"""
AS2 Message Orchestrator.

Handles the *preparation* of an outbound AS2 message:
  - resolving cryptographic material from Vault
  - building sign/encrypt callables via functools.partial
  - constructing the RFC 4130 HTTP body and headers

Deliberately separated from DeliveryService so that each class has a
single reason to change (SRP):
  - DeliveryService changes when delivery routing rules change.
  - AS2MessageOrchestrator changes when AS2 crypto/protocol rules change.
"""

import functools

import structlog
from secret_store.ports.secret_store_port import SecretStorePort

from edi.adapters.inbound.as2.builder import build_outbound_message
from edi.adapters.outbound.security import encrypt_payload, sign_payload
from edi.application.dtos.partners import (
    AS2PartnershipDTO,
    LocalAS2PartnerDTO,
    RemoteAS2PartnerDTO,
)
from edi.domain.models.as2 import OutboundAS2Message

logger = structlog.get_logger(__name__)


async def _resolve_pem(
    vault_ref: str | None,
    inline_pem: str | None,
    vault: SecretStorePort | None,
) -> bytes | None:
    """
    Resolves a PEM value from the Vault (preferred) or from a stored inline string.
    Returns None if neither source is available.
    """
    if vault_ref:
        if not vault:
            raise RuntimeError("Vault reference configured but no VaultAdapter provided.")
        raw = await vault.get_secret(vault_ref)
        return raw.encode() if isinstance(raw, str) else raw
    if inline_pem:
        return inline_pem.encode()
    return None


class AS2MessageOrchestrator:
    """
    Responsible for one thing: given partner config and raw EDI bytes,
    produce a ready-to-transmit OutboundAS2Message.

    All crypto is delegated to the `security` library via functools.partial,
    keeping this class free of direct cryptographic logic.
    """

    def __init__(self, vault: SecretStorePort | None = None) -> None:
        self.secret_store = vault

    async def build(
        self,
        raw_payload: bytes,
        local_partner: LocalAS2PartnerDTO | None,
        remote_partner: RemoteAS2PartnerDTO,
        partnership: AS2PartnershipDTO,
        idempotency_key: str | None = None,
    ) -> OutboundAS2Message:
        """
        Builds the fully-wrapped AS2 HTTP message for transmission.

        Args:
            raw_payload:    Raw EDI bytes from S3.
            local_partner:  Local AS2 partner DTO (for signing key/cert).
            remote_partner: Remote AS2 partner DTO.
            partnership:    AS2 Partnership DTO containing negotiated settings.

        Returns:
            OutboundAS2Message with `.body`, `.headers`, and `.mic`.

        Raises:
            ValueError: If the local AS2 identity cannot be resolved.
        """
        if not local_partner:
            raise ValueError(
                "Local AS2 partner config is missing. "
                "The AS2Partnership must have a valid local_partner_id."
            )

        if not local_partner.as2_id:
            raise ValueError("Missing 'as2_id' in local AS2 partner configuration.")
        if not remote_partner.as2_id:
            raise ValueError("Missing 'as2_id' in remote AS2 partner configuration.")

        local_as2_id: str = local_partner.as2_id
        remote_as2_id: str = remote_partner.as2_id

        # ── Resolve cryptographic material from Vault ─────────────────────────
        local_private_key_pem = await _resolve_pem(
            local_partner.private_key_vault_ref,
            None,  # private keys must come from Vault, never stored inline
            self.secret_store,
        )
        local_cert_pem = await _resolve_pem(
            local_partner.public_cert_vault_ref,
            local_partner.public_cert_pem,
            self.secret_store,
        )
        remote_cert_pem = await _resolve_pem(
            remote_partner.public_cert_vault_ref,
            remote_partner.public_cert_pem,
            self.secret_store,
        )

        # ── Build sign / encrypt callables via functools.partial ──────────────
        #    sign_payload(payload, private_key_pem, public_cert_pem)
        #    encrypt_payload(payload, public_cert_pem, algorithm)
        #    partial pre-fills the trailing keyword args; builder supplies payload as first positional.
        sign_fn = (
            functools.partial(
                sign_payload,
                private_key_pem=local_private_key_pem,
                public_cert_pem=local_cert_pem,
            )
            if (local_private_key_pem and local_cert_pem)
            else None
        )

        encryption_alg: str = partnership.encryption_algorithm or "AES256"
        encrypt_fn = (
            functools.partial(
                encrypt_payload,
                public_cert_pem=remote_cert_pem,
                algorithm=encryption_alg,
            )
            if remote_cert_pem
            else None
        )

        # ── Determine MDN mode ────────────────────────────────────────────────
        mdn_type: str = partnership.mdn_type or "SYNC"
        mdn_url: str | None = partnership.mdn_url if mdn_type == "ASYNC" else None

        return build_outbound_message(
            payload=raw_payload,
            as2_from=local_as2_id,
            as2_to=remote_as2_id,
            sign_fn=sign_fn,
            encrypt_fn=encrypt_fn,
            mdn_url=mdn_url,
            message_id=idempotency_key,
        )
