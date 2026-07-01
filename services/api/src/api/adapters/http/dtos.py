from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, model_validator

# ---------------------------------------------------------------------------
# Partner Creation Requests
# ---------------------------------------------------------------------------


class CreateAS2TradingPartnerRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Name of the AS2 Trading Partner")
    as2_id: str = Field(..., max_length=255, description="AS2 ID for the partner")
    is_local: bool = Field(False, description="Is this a local station?")
    public_cert_pem: str | None = Field(None, description="Public certificate in PEM format")
    public_cert_vault_ref: str | None = Field(
        None, max_length=512, description="Vault reference for public cert"
    )
    private_key_vault_ref: str | None = Field(
        None, max_length=512, description="Vault reference for private key (Local only)"
    )


class CreateAS2PartnershipRequest(BaseModel):
    local_partner_id: UUID = Field(..., description="ID of the local identity")
    remote_partner_id: UUID = Field(..., description="ID of the remote identity")
    remote_url: HttpUrl | None = Field(None, description="Remote AS2 URL")
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
    remote_path: str | None = Field(None, max_length=1024, description="Remote directory path")
    credentials_vault_ref: str = Field(
        ..., max_length=512, description="Vault reference for password/key"
    )


class CreateWebhookPartnerRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Name of the Webhook partner")
    url: HttpUrl = Field(..., description="Webhook endpoint URL")
    auth_header_vault_ref: str | None = Field(
        None, max_length=512, description="Vault reference for auth header"
    )


# ---------------------------------------------------------------------------
# Route Creation Requests
# ---------------------------------------------------------------------------


class CreateInboundRouteRequest(BaseModel):
    isa_sender_id: str = Field(..., max_length=255, description="ISA Sender ID to match")
    isa_receiver_id: str = Field(..., max_length=255, description="ISA Receiver ID to match")
    transaction_type: str = Field(
        ..., max_length=50, description="EDI Transaction Type (e.g., '204', '990', or '*')"
    )
    webhook_partner_id: UUID | None = Field(
        None, description="ID of Webhook Partner for transformation routing"
    )
    as2_partner_id: UUID | None = Field(None, description="ID of AS2 Partner for Direct Bridging")
    sftp_partner_id: UUID | None = Field(None, description="ID of SFTP Partner for Direct Bridging")

    @model_validator(mode="after")
    def check_exactly_one_destination(self) -> "CreateInboundRouteRequest":
        targets = [
            self.webhook_partner_id is not None,
            self.as2_partner_id is not None,
            self.sftp_partner_id is not None,
        ]
        if sum(targets) != 1:
            raise ValueError("Exactly one destination partner must be specified")
        return self


class CreateOutboundRouteRequest(BaseModel):
    isa_sender_id: str = Field(..., max_length=255, description="ISA Sender ID to match")
    isa_receiver_id: str = Field(..., max_length=255, description="ISA Receiver ID to match")
    transaction_type: str = Field(
        ..., max_length=50, description="EDI Transaction Type (e.g., '204', '990', or '*')"
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


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class PartnerResponse(BaseModel):
    partner_id: UUID
    tenant_id: int
    type: str  # AS2, SFTP, WEBHOOK
    status: str


class AS2TradingPartnerResponse(BaseModel):
    id: str
    name: str
    type: str = "AS2"
    as2_id: str
    is_local: bool


class AS2PartnershipResponse(BaseModel):
    id: str
    local_partner_id: str
    remote_partner_id: str
    local_url: str | None = None
    remote_url: str | None = None
    mdn_type: str
    mdn_url: str | None = None
    encryption_algorithm: str
    signature_algorithm: str
    edi_version: str | None = None
    status: str


class RouteResponse(BaseModel):
    route_id: UUID
    tenant_id: int
    direction: str  # INBOUND, OUTBOUND


class RouteItemResponse(BaseModel):
    route_id: UUID
    direction: str
    isa_sender_id: str
    isa_receiver_id: str
    destination_type: str
    destination_name: str
    status: str = "Active"
