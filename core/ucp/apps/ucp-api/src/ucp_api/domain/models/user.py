from datetime import datetime, timezone
from typing import Literal, Optional
from ucp_api.domain.models.aggregate_root import AggregateRoot


class User(AggregateRoot):
    ID_PREFIX = "usr"

    def __init__(
        self,
        id: str,
        idp_user_id: Optional[str],
        email: str,
        name: str,
        status: Literal["active", "inactive"],
        created_at: datetime,
        updated_at: datetime,
    ):
        super().__init__()
        self.id = id
        self.idp_user_id = idp_user_id
        self.email = email
        self.name = name
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at

    @classmethod
    def create(
        cls,
        id: str,
        idp_user_id: Optional[str],
        email: str,
        name: str,
    ) -> "User":
        now = datetime.now(timezone.utc)
        return cls(
            id=id,
            idp_user_id=idp_user_id,
            email=email,
            name=name,
            status="active",
            created_at=now,
            updated_at=now,
        )

    def activate(self) -> None:
        if self.status != "active":
            self.status = "active"
            self.updated_at = datetime.now(timezone.utc)

    def deactivate(self) -> None:
        if self.status != "inactive":
            self.status = "inactive"
            self.updated_at = datetime.now(timezone.utc)
