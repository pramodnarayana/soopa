from enum import StrEnum


class DeploymentEnvironment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"
    STAGING = "staging"


class LifecycleStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
