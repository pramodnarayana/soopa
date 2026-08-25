from pydantic import BaseModel, Field


class ZitadelRole(BaseModel):
    key: str
    display_name: str | None = Field(None, alias="displayName")
    group: str | None = None


class ZitadelProjectGrant(BaseModel):
    grant_id: str | None = Field(None, alias="grantId")
    id: str | None = None
    granted_org_id: str | None = Field(None, alias="grantedOrgId")
    project_id: str | None = Field(None, alias="projectId")
    role_keys: list[str] | None = Field(None, alias="roleKeys")
    user_id: str | None = Field(None, alias="userId")


class ZitadelUser(BaseModel):
    user_id: str | None = Field(None, alias="userId")
    id: str | None = None
    email: str | None = None
    display_name: str | None = Field(None, alias="displayName")
    first_name: str | None = Field(None, alias="firstName")
    last_name: str | None = Field(None, alias="lastName")
    state: str | None = None
    role: str | None = None
    created_at: str | None = Field(None, alias="createdAt")


class ZitadelEmail(BaseModel):
    email: str | None = None


class ZitadelProfile(BaseModel):
    display_name: str | None = Field(None, alias="displayName")
    first_name: str | None = Field(None, alias="firstName")
    last_name: str | None = Field(None, alias="lastName")


class ZitadelHuman(BaseModel):
    email: ZitadelEmail | None = None
    profile: ZitadelProfile | None = None


class ZitadelDetails(BaseModel):
    creation_date: str | None = Field(None, alias="creationDate")
    total_result: int | None = Field(None, alias="totalResult")
    view_timestamp: str | None = Field(None, alias="viewTimestamp")


class ZitadelRawUser(BaseModel):
    id: str
    user_name: str | None = Field(None, alias="userName")
    state: str | None = None
    human: ZitadelHuman | None = None
    details: ZitadelDetails | None = None


class ZitadelRawUserSearchResponse(BaseModel):
    result: list[ZitadelRawUser] = Field(default_factory=list)


class ZitadelRolesResponse(BaseModel):
    details: ZitadelDetails | None = None
    result: list[ZitadelRole] = Field(default_factory=list)


class ZitadelProjectGrantsResponse(BaseModel):
    details: ZitadelDetails | None = None
    result: list[ZitadelProjectGrant] = Field(default_factory=list)
