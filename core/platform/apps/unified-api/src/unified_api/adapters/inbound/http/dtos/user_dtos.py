"""HTTP-layer request/response DTOs for the Users resource.

These Pydantic models are the API contract — they live at the HTTP boundary and
must NOT be imported from the Application or Domain layers.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class UserStateResponse(StrEnum):
    """External API state representation for a user.

    Maps internal domain UserStatus to the Zitadel-compatible state strings
    exposed in the HTTP response contract.
    """

    ACTIVE = "USER_STATE_ACTIVE"
    INACTIVE = "USER_STATE_INACTIVE"


class CreateUserRequest(BaseModel):
    """Request body for POST /tenants/{tenant_id}/users/."""

    first_name: str = Field(..., alias="firstName", min_length=1)
    last_name: str = Field(..., alias="lastName", min_length=1)
    email: EmailStr
    role: str = Field(..., min_length=1)


class UpdateUserRequest(BaseModel):
    """Request body for PATCH /tenants/{tenant_id}/users/{user_id}."""

    first_name: str = Field(..., alias="firstName", min_length=1)
    last_name: str = Field(..., alias="lastName", min_length=1)
    role: str = Field(..., min_length=1)


class ToggleUserStatusRequest(BaseModel):
    """Request body for PATCH /tenants/{tenant_id}/users/{user_id}/status."""

    action: Literal["activate", "deactivate"]


class UserResponse(BaseModel):
    """Response shape for individual User returned in lists."""

    id: str
    email: str
    display_name: str = Field(alias="displayName")
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    state: UserStateResponse
    role: str
    created_at: str = Field(alias="createdAt")
