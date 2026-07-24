from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

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
    private_key_pem: str | None = Field(
        None, description="Raw private key PEM to store in Vault on creation (Local only)"
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
    host_key: str | None = Field(None, description="Host key for SFTP verification")


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


class TestAS2ConnectionRequest(BaseModel):
    custom_payload: str | None = Field(None, description="Optional custom EDI payload to send")


class TestAS2ConnectionResponse(BaseModel):
    success: bool
    mdn_disposition: str | None = None
    reason: str | None = None
    sent_payload: str | None = None
    raw_mdn: str | None = None


class CreateWebhookRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Name of the Webhook partner")
    url: HttpUrl = Field(..., description="Webhook endpoint URL")
    auth_header_vault_ref: str | None = Field(
        None, max_length=512, description="Vault reference for auth header"
    )

    @field_validator("url")
    @classmethod
    def validate_no_loopback(_cls, v: HttpUrl) -> HttpUrl:
        if v.host in ("127.0.0.1", "localhost", "::1") or (
            v.host and v.host.startswith("169.254.")
        ):
            raise ValueError("Loopback or link-local addresses are not permitted for webhooks.")
        return v


class UpdateWebhookRequest(BaseModel):
    name: str | None = Field(None, max_length=255, description="Name of the Webhook partner")
    active: bool | None = Field(None, description="Active status of the Webhook partner")
    url: HttpUrl | None = Field(None, description="Receiving URL for the Webhook")


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
    host_key: str | None = Field(None, description="Host key for SFTP verification")
    active: bool | None = None


# ---------------------------------------------------------------------------
# Route Creation Requests
# ---------------------------------------------------------------------------


class CreateInboundRouteRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Name of the route")
    trading_partner_id: str | None = Field(
        None, max_length=255, description="Trading Partner ID for internal routing"
    )
    isa_sender_id: str = Field(..., max_length=255, description="ISA Sender ID to match")
    isa_receiver_id: str = Field(..., max_length=255, description="ISA Receiver ID to match")
    gs_sender_id: str | None = Field(None, max_length=255, description="GS Sender ID to match")
    gs_receiver_id: str | None = Field(None, max_length=255, description="GS Receiver ID to match")
    transaction_type: str = Field(
        ..., max_length=50, description="EDI Transaction Type (e.g., '204', '990', or '*')"
    )
    processing_mode: Literal["TRANSFORM", "PASSTHROUGH"] = Field(
        "TRANSFORM", description="Processing Mode"
    )
    webhook_id: UUID | None = Field(
        None, description="ID of Webhook Partner for transformation routing"
    )
    as2_partner_id: UUID | None = Field(None, description="ID of AS2 Partner for Direct Bridging")
    sftp_partner_id: UUID | None = Field(None, description="ID of SFTP Partner for Direct Bridging")


class CreateOutboundRouteRequest(BaseModel):
    trading_partner_id: str = Field(
        ..., max_length=255, description="The ERP's identifier for this route"
    )
    name: str = Field(..., max_length=255, description="Name of the route")
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


class CreateOutboundEdiHeaderRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Name of the header mapping")
    trading_partner_id: str = Field(
        ..., max_length=255, description="The ERP's identifier for this route"
    )
    isa_sender_id: str = Field(..., max_length=255, description="ISA Sender ID to map")
    isa_sender_qualifier: str | None = Field(None, max_length=2, description="ISA Sender Qualifier")
    isa_receiver_id: str = Field(..., max_length=255, description="ISA Receiver ID to map")
    isa_receiver_qualifier: str | None = Field(
        None, max_length=2, description="ISA Receiver Qualifier"
    )
    gs_sender_id: str = Field(..., max_length=255, description="GS Sender ID to map")
    gs_receiver_id: str = Field(..., max_length=255, description="GS Receiver ID to map")
    transaction_type: str = Field(
        ..., max_length=50, description="EDI Transaction Type (e.g., '204', '990', or '*')"
    )
    default_standard: str = Field("x12", max_length=50, description="EDI Standard")
    default_version: str = Field("004010", max_length=50, description="EDI Version")


class UpdateOutboundEdiHeaderRequest(BaseModel):
    name: str | None = Field(None, max_length=255, description="Name of the header mapping")
    trading_partner_id: str | None = Field(None, max_length=255, description="Trading Partner ID")
    isa_sender_id: str | None = Field(None, max_length=255, description="ISA Sender ID to match")
    isa_sender_qualifier: str | None = Field(
        None, max_length=2, description="ISA Sender Qualifier (Outbound only)"
    )
    isa_receiver_id: str | None = Field(
        None, max_length=255, description="ISA Receiver ID to match"
    )
    isa_receiver_qualifier: str | None = Field(
        None, max_length=2, description="ISA Receiver Qualifier (Outbound only)"
    )
    gs_sender_id: str | None = Field(None, max_length=255, description="GS Sender ID")
    gs_receiver_id: str | None = Field(None, max_length=255, description="GS Receiver ID")
    transaction_type: str | None = Field(None, max_length=50, description="EDI Transaction Type")
    default_standard: str | None = Field(
        None, max_length=50, description="EDI Standard (Outbound only)"
    )
    default_version: str | None = Field(
        None, max_length=50, description="EDI Version (Outbound only)"
    )


class UpdateRouteRequest(BaseModel):
    active: bool | None = None
    name: str | None = Field(None, max_length=255, description="Name of the route")
    trading_partner_id: str | None = Field(None, max_length=255, description="Trading Partner ID")
    isa_sender_id: str | None = Field(None, max_length=255, description="ISA Sender ID to match")
    isa_sender_qualifier: str | None = Field(
        None, max_length=2, description="ISA Sender Qualifier (Outbound only)"
    )
    isa_receiver_id: str | None = Field(
        None, max_length=255, description="ISA Receiver ID to match"
    )
    isa_receiver_qualifier: str | None = Field(
        None, max_length=2, description="ISA Receiver Qualifier (Outbound only)"
    )
    gs_sender_id: str | None = Field(None, max_length=255, description="GS Sender ID")
    gs_receiver_id: str | None = Field(None, max_length=255, description="GS Receiver ID")
    default_standard: str | None = Field(
        None, max_length=50, description="EDI Standard (Outbound only)"
    )
    default_version: str | None = Field(
        None, max_length=50, description="EDI Version (Outbound only)"
    )
    transaction_type: str | None = Field(
        None, max_length=50, description="EDI Transaction Type (e.g., '204', '990', or '*')"
    )
    processing_mode: Literal["TRANSFORM", "PASSTHROUGH"] | None = Field(
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
    host_key: str | None = None

    def model_post_init(self, _context: Any) -> None:
        if self.id is None:
            object.__setattr__(self, "id", self.partner_id)


class GenerateCertRequest(BaseModel):
    as2_id: str = Field(..., max_length=255, description="AS2 ID to use as Common Name")


class GenerateCertResponse(BaseModel):
    public_cert_pem: str = Field(..., description="Public certificate in PEM format")
    private_key_vault_ref: str = Field(
        ..., description="Vault reference for the generated private key"
    )


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
    trading_partner_id: str | None = None
    name: str | None = None
    local_partner_id: str
    remote_partner_id: str
    mdn_type: str
    mdn_url: str | None = None
    encryption_algorithm: str
    signature_algorithm: str

    status: str
    active: bool = False


class RouteResponse(BaseModel):
    route_id: UUID
    tenant_id: int
    direction: str  # INBOUND, OUTBOUND


class BaseRouteItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    route_id: UUID
    trading_partner_id: str | None = None
    name: str
    destination_type: str
    destination_name: str
    webhook_id: UUID | None = None
    as2_partner_id: UUID | None = None
    sftp_partner_id: UUID | None = None
    status: str = Field(default="ACTIVE")
    active: bool = False


class InboundRouteItem(BaseRouteItem):
    direction: Literal["INBOUND"]
    isa_sender_id: str
    isa_sender_qualifier: str | None = None
    isa_receiver_id: str
    isa_receiver_qualifier: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    default_standard: str | None = None
    default_version: str | None = None
    transaction_type: str
    processing_mode: str = "TRANSFORM"


class OutboundRouteItem(BaseRouteItem):
    direction: Literal["OUTBOUND"]
    transaction_type: str = "*"


RouteItemResponse = Annotated[
    InboundRouteItem | OutboundRouteItem, Field(discriminator="direction")
]


class OutboundMessageRequest(BaseModel):
    trading_partner_id: str = Field(
        ..., description="The ERP's identifier for the routing rule (trading_partner_id)"
    )
    payload: dict[str, Any] | list[dict[str, Any]] = Field(
        ..., description="The JSON payload representing the EDI document(s)"
    )
    transaction_type: str | None = Field(
        None, max_length=50, description="The EDI transaction type, e.g., '204', '850'"
    )


class OutboundMessageResponse(BaseModel):
    trace_id: UUID = Field(..., description="The Trace ID to track the message lifecycle")
    status: str = Field(default="ACCEPTED")


# ---------------------------------------------------------------------------
# API Token DTOs
# ---------------------------------------------------------------------------


class CreateApiTokenRequest(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable label for this token (e.g. 'ERP Integration Prod')",
    )
    expires_at: datetime | None = Field(
        None, description="Optional ISO-8601 expiry datetime. Null = never expires."
    )


class UpdateApiTokenRequest(BaseModel):
    name: str | None = Field(
        None, min_length=1, max_length=255, description="Human-readable label for this token"
    )
    active: bool | None = Field(None, description="Whether the token is active")


class ApiTokenCreatedResponse(BaseModel):
    """
    Returned exactly once upon token creation.
    client_secret is shown here and NEVER returned again.
    """

    id: UUID
    name: str
    client_id: str = Field(
        ..., description="Plaintext client identifier — safe to display in UI and logs"
    )
    client_secret: str = Field(
        ..., description="Raw client secret — store immediately, shown ONCE only"
    )
    active: bool
    created_at: str


class ApiTokenListItem(BaseModel):
    """Safe list representation — secret is never included."""

    id: UUID
    name: str
    client_id: str
    active: bool
    last_used_at: str | None
    expires_at: str | None
    created_at: str


class ApiTokenListResponse(BaseModel):
    tokens: list[ApiTokenListItem]
