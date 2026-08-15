"""HTTP-layer request/response DTOs for the Users resource.

These Pydantic models are the API contract — they live at the HTTP boundary and
must NOT be imported from the Application or Domain layers.
"""

from pydantic import AliasChoices, BaseModel, EmailStr, Field


class CreateUserRequest(BaseModel):
    """Request body for POST /tenants/{tenant_id}/users/."""

    first_name: str = Field(
        ..., validation_alias=AliasChoices("firstName", "first_name"), min_length=1
    )
    last_name: str = Field(
        ..., validation_alias=AliasChoices("lastName", "last_name"), min_length=1
    )
    email: EmailStr
    role: str = Field(..., min_length=1)


class UpdateUserRequest(BaseModel):
    """Request body for PATCH /tenants/{tenant_id}/users/{user_id}."""

    first_name: str = Field(
        ..., validation_alias=AliasChoices("firstName", "first_name"), min_length=1
    )
    last_name: str = Field(
        ..., validation_alias=AliasChoices("lastName", "last_name"), min_length=1
    )
    role: str = Field(..., min_length=1)


class ToggleUserStatusRequest(BaseModel):
    """Request body for PATCH /tenants/{tenant_id}/users/{user_id}/status."""

    action: str = Field(..., pattern="^(activate|deactivate)$")


class UserResponse(BaseModel):
    """Response shape for individual User returned in lists."""

    id: str
    email: str
    display_name: str = Field(validation_alias="displayName")
    first_name: str = Field(validation_alias="firstName")
    last_name: str = Field(validation_alias="lastName")
    state: str
    role: str
    created_at: str = Field(validation_alias="createdAt")
