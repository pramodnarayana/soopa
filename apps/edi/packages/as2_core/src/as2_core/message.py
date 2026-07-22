from dataclasses import dataclass, field


@dataclass
class AS2Message:
    """
    Pure data representation of an AS2 Message.
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
