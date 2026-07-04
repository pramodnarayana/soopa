from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

# ---------------------------------------------------------------------------
# Partner Creation Requests
# ---------------------------------------------------------------------------


class CreateAS2TradingPartnerRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Name of the AS2 Trading Partner")
    as2_id: str = Field(..., max_length=255, description="AS2 ID for the partner")
    is_local: bool = Field(False, description="Is this a local station?")
    url: HttpUrl | None = Field(None, description="Receiving URL for this Trading Partner")
    public_cert_pem: str | None = Field(None, description="Public certificate in PEM format")
    public_cert_vault_ref: str | None = Field(
        None, max_length=512, description="Vault reference for public cert"
    )
    private_key_vault_ref: str | None = Field(
        None, max_length=512, description="Vault reference for private key (Local only)"
    )


class CreateAS2PartnershipRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Name for the partnership")
    local_partner_id: UUID = Field(..., description="ID of the local identity")
    remote_partner_id: UUID = Field(..., description="ID of the remote identity")
    credentials_vault_ref: str | None = Field(
        None, max_length=512, description="Vault reference for basic auth"
    )
    mdn_type: str = Field("SYNC", max_length=50, description="MDN Type (SYNC, ASYNC, NONE)")
    mdn_url: HttpUrl | None = Field(None, description="MDN URL for ASYNC")
    encryption_algorithm: str = Field("AES256", max_length=50, description="Encryption Algorithm")
    signature_algorithm: str = Field("SHA256", max_length=50, description="Signature Algorithm")
    edi_version: Literal["X12-004010", "X12-005010", "EDIFACT-D96A", "EDIFACT-D01B"] | None = Field(
        None, description="EDI Version (e.g. X12 5010)"
    )
    advanced_flags: dict[str, Any] | None = Field(None, description="Advanced OpenAS2 JSON flags")


class CreateSFTPPartnerRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Name of the SFTP partner")
    host: str = Field(..., max_length=1024, description="Host URL or IP")
    port: int = Field(22, ge=1, le=65535, description="Valid TCP port (1-65535)")
    username: str = Field(..., max_length=255, description="SFTP username")
    inbound_remote_path: str | None = Field(
        None, max_length=1024, description="Inbound remote directory path"
    )
    outbound_remote_path: str | None = Field(
        None, max_length=1024, description="Outbound remote directory path"
    )
    password: str | None = Field(
        None, max_length=1024, description="Password to authenticate with the SFTP server"
    )
    credentials_vault_ref: str | None = Field(
        None, max_length=512, description="Vault reference for SSH private key"
    )


class TestSFTPConnectionRequest(BaseModel):
    host: str = Field(..., max_length=1024, description="Host URL or IP")
    port: int = Field(22, ge=1, le=65535, description="Valid TCP port (1-65535)")
    username: str = Field(..., max_length=255, description="SFTP username")
    password: str | None = Field(
        None, max_length=1024, description="Password to authenticate with the SFTP server"
    )
    credentials_vault_ref: str | None = Field(
        None, max_length=512, description="Vault reference for SSH private key"
    )


class TestConnectionResponse(BaseModel):
    success: bool
    reason: str | None = None


class CreateWebhookRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Name of the Webhook partner")
    url: HttpUrl = Field(..., description="Webhook endpoint URL")
    auth_header_vault_ref: str | None = Field(
        None, max_length=512, description="Vault reference for auth header"
    )

    @field_validator("url")
    @classmethod
    def validate_no_loopback(cls, v: HttpUrl) -> HttpUrl:
        if v.host in ("127.0.0.1", "localhost", "::1") or (
            v.host and v.host.startswith("169.254.")
        ):
            raise ValueError("Loopback or link-local addresses are not permitted for webhooks.")
        return v


class UpdateAS2TradingPartnerRequest(BaseModel):
    name: str | None = Field(None, max_length=255, description="Name of the trading partner")
    as2_id: str | None = Field(None, max_length=255, description="AS2 ID (local or remote)")
    is_local: bool | None = Field(
        None, description="True if local station, False if remote station"
    )
    url: HttpUrl | None = Field(None, description="Receiving URL for this Trading Partner")
    active: bool | None = None


class UpdateAS2PartnershipRequest(BaseModel):
    name: str | None = Field(None, max_length=255)
    local_partner_id: UUID | None = None
    remote_partner_id: UUID | None = None
    credentials_vault_ref: str | None = Field(None, max_length=255)
    mdn_type: Literal["SYNC", "ASYNC", "NONE"] | None = Field(None)
    mdn_url: HttpUrl | None = Field(None)
    encryption_algorithm: str | None = Field(None, max_length=50)
    signature_algorithm: str | None = Field(None, max_length=50)
    edi_version: (
        Literal["X12-004010", "X12-005010", "EDIFACT-D96A", "EDIFACT-D01B", "NONE"] | None
    ) = Field(None)
    advanced_flags: dict[str, Any] | None = Field(None)
    active: bool | None = Field(None)


class UpdateSFTPPartnerRequest(BaseModel):
    name: str | None = Field(None, max_length=255, description="Name of the SFTP partner")
    host: str | None = Field(None, max_length=255, description="SFTP host/IP")
    port: int | None = Field(None, description="SFTP port")
    username: str | None = Field(None, max_length=255, description="SFTP username")
    inbound_remote_path: str | None = Field(
        None, max_length=1024, description="Inbound path to poll"
    )
    outbound_remote_path: str | None = Field(
        None, max_length=1024, description="Outbound path to drop"
    )
    password: str | None = Field(
        None, max_length=1024, description="Password to authenticate with the SFTP server"
    )
    credentials_vault_ref: str | None = Field(
        None, max_length=512, description="Vault reference for password/key"
    )
    active: bool | None = None


# ---------------------------------------------------------------------------
# Route Creation Requests
# ---------------------------------------------------------------------------


class CreateInboundRouteRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Name of the route")
    isa_sender_id: str = Field(..., max_length=255, description="ISA Sender ID to match")
    isa_receiver_id: str = Field(..., max_length=255, description="ISA Receiver ID to match")
    transaction_type: str = Field(
        ..., max_length=50, description="EDI Transaction Type (e.g., '204', '990', or '*')"
    )
    processing_mode: Literal["TRANSLATE", "PASSTHROUGH"] = Field(
        "TRANSLATE", description="Processing Mode"
    )
    webhook_id: UUID | None = Field(
        None, description="ID of Webhook Partner for transformation routing"
    )
    as2_partner_id: UUID | None = Field(None, description="ID of AS2 Partner for Direct Bridging")
    sftp_partner_id: UUID | None = Field(None, description="ID of SFTP Partner for Direct Bridging")

    @model_validator(mode="after")
    def check_exactly_one_destination(self) -> "CreateInboundRouteRequest":
        targets = [
            self.webhook_id is not None,
            self.as2_partner_id is not None,
            self.sftp_partner_id is not None,
        ]
        if sum(targets) != 1:
            raise ValueError("Exactly one destination partner must be specified")
        return self


class CreateOutboundRouteRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Name of the route")
    isa_sender_id: str = Field(..., max_length=255, description="ISA Sender ID to match")
    isa_receiver_id: str = Field(..., max_length=255, description="ISA Receiver ID to match")
    transaction_type: str = Field(
        ..., max_length=50, description="EDI Transaction Type (e.g., '204', '990', or '*')"
    )
    processing_mode: Literal["TRANSLATE", "PASSTHROUGH"] = Field(
        "TRANSLATE", description="Processing Mode"
    )
    as2_partner_id: UUID | None = Field(None, description="ID of AS2 Partner for routing")
    sftp_partner_id: UUID | None = Field(None, description="ID of SFTP Partner for routing")

    @model_validator(mode="after")
    def check_exactly_one_destination(self) -> "CreateOutboundRouteRequest":
        targets = [
            self.as2_partner_id is not None,
            self.sftp_partner_id is not None,
        ]
        if sum(targets) != 1:
            raise ValueError("Exactly one destination partner must be specified")
        return self


class UpdateRouteRequest(BaseModel):
    active: bool | None = None
    name: str | None = Field(None, max_length=255, description="Name of the route")
    isa_sender_id: str | None = Field(None, max_length=255, description="ISA Sender ID to match")
    isa_receiver_id: str | None = Field(
        None, max_length=255, description="ISA Receiver ID to match"
    )
    transaction_type: str | None = Field(
        None, max_length=50, description="EDI Transaction Type (e.g., '204', '990', or '*')"
    )
    processing_mode: Literal["TRANSLATE", "PASSTHROUGH"] | None = Field(
        None, description="Processing Mode"
    )
    webhook_id: UUID | None = Field(
        None, description="ID of Webhook Partner for transformation routing"
    )
    as2_partner_id: UUID | None = Field(None, description="ID of AS2 Partner for routing")
    sftp_partner_id: UUID | None = Field(None, description="ID of SFTP Partner for routing")


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class PartnerResponse(BaseModel):
    partner_id: UUID
    id: UUID | None = None
    tenant_id: int
    name: str
    type: str  # AS2, SFTP, WEBHOOK
    status: str
    active: bool
    as2_id: str | None = None
    is_local: bool | None = None
    url: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    inbound_remote_path: str | None = None
    outbound_remote_path: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.id is None:
            object.__setattr__(self, "id", self.partner_id)


class AS2TradingPartnerResponse(BaseModel):
    id: str
    name: str
    type: str = "AS2"
    as2_id: str
    is_local: bool
    url: str | None = None
    active: bool = False


class RotateCertificateRequest(BaseModel):
    action: Literal["generate", "upload"] = Field(
        ..., description="Action to perform: generate or upload"
    )
    public_cert_pem: str | None = Field(None, description="Public certificate in PEM format")
    private_key_pem: str | None = Field(None, description="Private key in PEM format")


class CertificateExportResponse(BaseModel):
    public_cert_pem: str | None = None
    private_key_pem: str | None = None
    prev_public_cert_pem: str | None = None
    prev_private_key_pem: str | None = None


class AS2PartnershipResponse(BaseModel):
    id: str
    tenant_id: int | None
    name: str | None = None
    local_partner_id: str
    remote_partner_id: str
    mdn_type: str
    mdn_url: str | None = None
    encryption_algorithm: str
    signature_algorithm: str
    edi_version: str | None = None
    status: str
    active: bool = False


class RouteResponse(BaseModel):
    route_id: UUID
    tenant_id: int
    direction: str  # INBOUND, OUTBOUND


class RouteItemResponse(BaseModel):
    route_id: UUID
    name: str
    direction: str
    isa_sender_id: str
    isa_receiver_id: str
    transaction_type: str
    destination_type: str
    destination_name: str
    webhook_id: UUID | None = None
    as2_partner_id: UUID | None = None
    sftp_partner_id: UUID | None = None
    status: str = "Active"
    active: bool = False
    processing_mode: str = "TRANSLATE"
