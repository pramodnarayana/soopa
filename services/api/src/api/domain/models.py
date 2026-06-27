from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class CreateTradingPartnerRequest(BaseModel):
    partner_name: str = Field(..., max_length=255, description="Name of the trading partner")
    as2_id: str | None = Field(None, max_length=255, description="AS2 ID for the partner")
    direction: str = Field(..., description="INBOUND, OUTBOUND, or BOTH")

    # Connection details
    connection_type: str = Field(..., description="AS2, SFTP, FTP, WEBHOOK")
    host: str | None = Field(None, max_length=1024, description="Host URL or IP")
    port: int | None = Field(None, ge=1, le=65535, description="Valid TCP/UDP port (1-65535)")
    credentials_vault_ref: str = Field(
        ..., max_length=512, description="Reference to stored credentials in vault"
    )

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        allowed = {"INBOUND", "OUTBOUND", "BOTH"}
        if v.upper() not in allowed:
            raise ValueError(f"direction must be one of {allowed}")
        return v.upper()

    @field_validator("connection_type")
    @classmethod
    def validate_connection_type(cls, v: str) -> str:
        allowed = {"AS2", "SFTP", "FTP", "WEBHOOK"}
        if v.upper() not in allowed:
            raise ValueError(f"connection_type must be one of {allowed}")
        return v.upper()


class TradingPartnerResponse(BaseModel):
    trading_partner_id: UUID
    status: str
    tenant_id: int
