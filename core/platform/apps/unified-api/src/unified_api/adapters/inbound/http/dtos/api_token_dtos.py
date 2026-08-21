from datetime import datetime

from pydantic import BaseModel, Field


class ApiTokenResponse(BaseModel):
    id: str
    name: str
    client_id: str
    active: bool
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class ApiTokenCreatedResponse(ApiTokenResponse):
    token: str


class CreateApiTokenRequest(BaseModel):
    name: str = Field(..., max_length=255)
    expires_at: datetime | None = None


class UpdateApiTokenRequest(BaseModel):
    name: str | None = Field(None, max_length=255)
    active: bool | None = None
