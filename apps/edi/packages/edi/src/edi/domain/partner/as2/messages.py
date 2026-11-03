"""AS2 Protocol Wire Message & MDN Value Objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from edi.domain.partner.as2.enums import Disposition

AS2HeaderMap: TypeAlias = dict[str, str]

__all__ = [
    "AS2MDN",
    "AS2HeaderMap",
    "AS2Message",
    "Disposition",
    "MDNResponse",
    "OutboundAS2Message",
]


@dataclass
class AS2Message:
    """Pure data representation of an inbound AS2 Message.

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
    """Pure data representation of an AS2 Message Disposition Notification (MDN)."""

    original_message_id: str
    disposition: str
    headers: dict[str, str] = field(default_factory=dict)
    mic: str | None = None
    is_signed: bool = False
    body: bytes = b""


@dataclass
class OutboundAS2Message:
    """Ready-to-transmit outbound AS2 HTTP message.

    Produced by the builder after crypto pipeline is applied.
    """

    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    mic: str | None = None


@dataclass
class MDNResponse:
    """The serialized MDN HTTP response: body bytes and response headers."""

    body: bytes
    headers: dict[str, str]
