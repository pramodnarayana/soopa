from dataclasses import dataclass


@dataclass(frozen=True)
class OpenObserveConstants:
    DEFAULT_ADMIN_EMAIL: str = "admin@example.com"
    DEFAULT_PROD_RETENTION_DAYS: int = 30
    DEFAULT_NON_PROD_RETENTION_DAYS: int = 3
