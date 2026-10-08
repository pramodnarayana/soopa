from dataclasses import dataclass


@dataclass(frozen=True)
class OpenObserveConstants:
    DEFAULT_ADMIN_EMAIL: str = "admin@example.com"
