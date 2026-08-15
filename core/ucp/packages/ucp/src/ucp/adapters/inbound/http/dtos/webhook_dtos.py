from pydantic import BaseModel, Field, HttpUrl


class CreateWebhookRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Name for the webhook destination")
    url: HttpUrl = Field(..., description="Target delivery URL")
    auth_header_vault_ref: str | None = Field(
        None, max_length=512, description="Vault reference for custom auth headers"
    )


class UpdateWebhookRequest(BaseModel):
    name: str | None = Field(None, max_length=255, description="Name for the webhook destination")
    url: HttpUrl | None = Field(None, description="Target delivery URL")
    active: bool | None = Field(None, description="Whether the webhook is active")


class WebhookResponse(BaseModel):
    webhook_id: str
    tenant_id: str
    name: str
    url: str | None
    active: bool
