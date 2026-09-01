from enum import StrEnum


class DatabaseShardStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
