import os
from datetime import UTC, datetime
from typing import Self

from seedwork.models import AggregateRoot

from ucp.domain.events import (
    WebhookCreatedEvent,
    WebhookUpdatedEvent,
)


class WebhookDomainModel(AggregateRoot):
    ID_PREFIX = "web"

    def __init__(
        self,
        id: str,
        tenant_id: str,
        name: str,
        url: str,
        auth_header_vault_ref: str | None,
        active: bool,
        created_at: datetime,
        updated_at: datetime,
    ):
        super().__init__()
        self.id = id
        self.tenant_id = tenant_id
        self.name = name
        self.url = url
        self.auth_header_vault_ref = auth_header_vault_ref
        self.active = active
        self.created_at = created_at
        self.updated_at = updated_at

    @classmethod
    def create(
        cls,
        tenant_id: str,
        name: str,
        url: str,
        auth_header_vault_ref: str | None,
    ) -> Self:
        now = datetime.now(UTC)
        webhook_id = f"{cls.ID_PREFIX}_{os.urandom(12).hex()}"

        webhook = cls(
            id=webhook_id,
            tenant_id=tenant_id,
            name=name,
            url=url,
            auth_header_vault_ref=auth_header_vault_ref,
            active=True,
            created_at=now,
            updated_at=now,
        )

        webhook.add_domain_event(WebhookCreatedEvent(tenant_id=tenant_id, webhook_id=webhook_id))

        return webhook

    def update(
        self,
        name: str | None = None,
        url: str | None = None,
        active: bool | None = None,
    ) -> None:
        changed = False
        if name is not None and self.name != name:
            self.name = name
            changed = True
        if url is not None and self.url != url:
            self.url = url
            changed = True
        if active is not None and self.active != active:
            self.active = active
            changed = True

        if changed:
            self.updated_at = datetime.now(UTC)
            self.add_domain_event(WebhookUpdatedEvent(tenant_id=self.tenant_id, webhook_id=self.id))
