from enum import StrEnum


class IdentityIdPrefix(StrEnum):
    TENANT = "iam_ten"
    USER = "iam_usr"
    TOKEN = "iam_tok"
    KEY = "iam_key"
    ROLE = "iam_rol"
    USER_ROLE = "iam_urol"
    OUTBOX = "iam_ob"
