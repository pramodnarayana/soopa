from __future__ import annotations

from dataclasses import dataclass

from seedwork.domain.types import JsonValue


@dataclass(frozen=True)
class LocalAS2PartnerDTO:
    """
    Maps to AS2Partner (is_local=True).
    Contains signing-relevant fields used by get_local_as2_partner.
    """

    id: str
    name: str
    as2_id: str
    private_key_vault_ref: str | None
    public_cert_vault_ref: str | None
    public_cert_pem: str | None
    prev_private_key_vault_ref: str | None
    prev_public_cert_vault_ref: str | None


@dataclass(frozen=True)
class RemoteAS2PartnerDTO:
    """
    Maps to AS2Partner (is_local=False).
    Contains delivery-relevant fields used in the JOIN result of get_as2_partner.
    """

    id: str
    name: str
    as2_id: str
    url: str | None
    public_cert_pem: str | None
    public_cert_vault_ref: str | None
    prev_public_cert_pem: str | None
    prev_public_cert_vault_ref: str | None


@dataclass(frozen=True)
class AS2PartnershipDTO:
    """
    Maps directly to the AS2Partnership table.
    Holds the negotiated settings between a local and remote partner pair.

    get_as2_partner returns: tuple[RemoteAS2PartnerDTO, AS2PartnershipDTO] | None
    Callers destructure: partner, partnership = result
    """

    id: str
    name: str
    local_partner_id: str
    remote_partner_id: str
    credentials_vault_ref: str | None
    encryption_algorithm: str
    signature_algorithm: str
    mdn_type: str
    mdn_url: str | None
    advanced_flags: dict[str, JsonValue] | None


@dataclass(frozen=True)
class SFTPPartnerDTO:
    """Maps to SFTPPartner table."""

    id: str
    name: str
    host: str
    username: str
    port: int
    inbound_remote_path: str | None
    outbound_remote_path: str | None
    host_key: str | None
    password: str | None
    credentials_vault_ref: str | None
    active: bool
