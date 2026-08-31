from enum import StrEnum


class IdentityIdPrefix(StrEnum):
    TENANT = "iam_ten"
    USER = "iam_usr"
    TOKEN = "iam_tok"
    KEY = "iam_key"
    ROLE = "iam_rol"
    USER_ROLE = "iam_urol"
    OUTBOX = "iam_ob"


class IdentityEventType(StrEnum):
    TENANT_PROVISIONED = "tenant.provisioned"
    USER_INVITED = "UserInvited"
    USER_UPDATED = "UserUpdated"
    USER_ROLE_ASSIGNED = "user_role_assigned"
    USER_STATUS_TOGGLED = "UserStatusToggled"
    USER_DELETED = "UserDeleted"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
