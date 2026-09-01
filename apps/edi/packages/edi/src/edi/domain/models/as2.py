"""
AS2 Domain Models.

Pure data representations of AS2 protocol entities.
These are domain value objects with no external dependencies — only the Python stdlib.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from seedwork.models import AggregateRoot


class Disposition(StrEnum):
    """AS2 MDN disposition strings as defined in RFC 4130."""

    PROCESSED = "automatic-action/MDN-sent-automatically; processed"
    DECRYPTION_FAILED = "automatic-action/MDN-sent-automatically; failed/decryption-failed"
    AUTHENTICATION_FAILED = "automatic-action/MDN-sent-automatically; failed/authentication-failed"
    INSUFFICIENT_SECURITY = (
        "automatic-action/MDN-sent-automatically; failed/insufficient-message-security"
    )


@dataclass
class AS2Message:
    """
    Pure data representation of an inbound AS2 Message.
    Constructed by the parser; consumed by the receiver service.
    """

    message_id: str
    as2_from: str
    as2_to: str
    headers: dict[str, str] = field(default_factory=dict)
    payload: bytes = b""
    is_encrypted: bool = False
    is_signed: bool = False
    is_compressed: bool = False
    raw_mime: bytes | None = None


@dataclass
class AS2MDN:
    """
    Pure data representation of an AS2 Message Disposition Notification (MDN).
    """

    original_message_id: str
    disposition: str
    headers: dict[str, str] = field(default_factory=dict)
    mic: str | None = None
    is_signed: bool = False
    body: bytes = b""


@dataclass
class OutboundAS2Message:
    """
    Ready-to-transmit outbound AS2 HTTP message.
    Produced by the builder after crypto pipeline is applied.
    """

    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    mic: str | None = None


@dataclass
class MDNResponse:
    """
    The serialized MDN HTTP response: body bytes and response headers.
    """

    body: bytes
    headers: dict[str, str]


@dataclass(kw_only=True)
class AS2PartnerDomainModel(AggregateRoot):
    ID_PREFIX = "as2"

    id: str
    as2_id: str
    name: str
    is_local: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: str | None = None
    public_cert_pem: str | None = None
    public_cert_vault_ref: str | None = None
    private_key_vault_ref: str | None = None
    prev_public_cert_pem: str | None = None
    prev_public_cert_vault_ref: str | None = None
    prev_private_key_vault_ref: str | None = None
    url: str | None = None
    active: bool = False


@dataclass(kw_only=True)
class AS2PartnershipDomainModel(AggregateRoot):
    ID_PREFIX = "pship"

    id: str
    name: str
    local_partner_id: str
    remote_partner_id: str
    mdn_type: str
    encryption_algorithm: str
    signature_algorithm: str
    created_at: datetime
    updated_at: datetime
    tenant_id: str | None = None
    credentials_vault_ref: str | None = None
    mdn_url: str | None = None
    advanced_flags: dict[str, Any] | None = None
    active: bool = False
