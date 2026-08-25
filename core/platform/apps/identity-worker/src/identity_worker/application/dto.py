from dataclasses import dataclass


@dataclass(frozen=True)
class IdpRole:
    key: str
    display_name: str
    group: str


@dataclass(frozen=True)
class IdpUser:
    id: str
    preferred_login_name: str
    email: str
    first_name: str
    last_name: str
    state: str
