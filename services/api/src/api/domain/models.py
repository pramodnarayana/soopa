from uuid import UUID

from pydantic import BaseModel, Field


class CreateTradingPartnerRequest(BaseModel):
    partner_name: str = Field(..., max_length=255, description="Name of the trading partner")
    as2_id: str | None = Field(None, max_length=255, description="AS2 ID for the partner")
    direction: str = Field(..., description="INBOUND, OUTBOUND, or BOTH")

    # Connection details
    connection_type: str = Field(..., description="AS2, SFTP, FTP, WEBHOOK")
    host: str | None = Field(None, description="Host URL or IP")
    port: int | None = Field(None, description="Connection port")
    credentials_vault_ref: str = Field(..., description="Reference to stored credentials in vault")


class TradingPartnerResponse(BaseModel):
    trading_partner_id: UUID
    status: str
    tenant_id: int
