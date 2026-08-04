from pydantic import BaseModel, Field
from typing import Optional

class ZitadelRole(BaseModel):
    key: str
    display_name: Optional[str] = Field(None, alias="displayName")
    group: Optional[str] = None

class ZitadelProjectGrant(BaseModel):
    grant_id: Optional[str] = Field(None, alias="grantId")
    id: Optional[str] = None
    granted_org_id: Optional[str] = Field(None, alias="grantedOrgId")
    project_id: Optional[str] = Field(None, alias="projectId")
    role_keys: Optional[list[str]] = Field(None, alias="roleKeys")
    user_id: Optional[str] = Field(None, alias="userId")

class ZitadelUser(BaseModel):
    user_id: Optional[str] = Field(None, alias="userId")
    id: Optional[str] = None
    email: Optional[str] = None
    display_name: Optional[str] = Field(None, alias="displayName")
    first_name: Optional[str] = Field(None, alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")
    state: Optional[str] = None
    role: Optional[str] = None
    created_at: Optional[str] = Field(None, alias="createdAt")

class ZitadelEmail(BaseModel):
    email: Optional[str] = None

class ZitadelProfile(BaseModel):
    display_name: Optional[str] = Field(None, alias="displayName")
    first_name: Optional[str] = Field(None, alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")

class ZitadelHuman(BaseModel):
    email: Optional[ZitadelEmail] = None
    profile: Optional[ZitadelProfile] = None

class ZitadelDetails(BaseModel):
    creation_date: Optional[str] = Field(None, alias="creationDate")
    total_result: Optional[int] = Field(None, alias="totalResult")
    view_timestamp: Optional[str] = Field(None, alias="viewTimestamp")

class ZitadelRawUser(BaseModel):
    id: str
    user_name: Optional[str] = Field(None, alias="userName")
    state: Optional[str] = None
    human: Optional[ZitadelHuman] = None
    details: Optional[ZitadelDetails] = None

class ZitadelRawUserSearchResponse(BaseModel):
    result: list[ZitadelRawUser] = Field(default_factory=list)

class ZitadelRolesResponse(BaseModel):
    details: Optional[ZitadelDetails] = None
    result: list[ZitadelRole] = Field(default_factory=list)

class ZitadelProjectGrantsResponse(BaseModel):
    details: Optional[ZitadelDetails] = None
    result: list[ZitadelProjectGrant] = Field(default_factory=list)
