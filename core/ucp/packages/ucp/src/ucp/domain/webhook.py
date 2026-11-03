"""Webhook Behavioral Aggregate Root for the UCP Bounded Context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar
from urllib.parse import urlparse

from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.exceptions import Result
from seedwork.domain.types import UNSET, UnsetType, resolve_unset

from ucp.domain.constants import UcpIdPrefix
from ucp.domain.events import (
    WebhookCreatedEvent,
    WebhookDeletedEvent,
    WebhookUpdatedEvent,
)
from ucp.domain.exceptions import (
    UcpError,
    UcpValidationError,
    WebhookAlreadyDeletedError,
)

__all__ = ["Webhook"]

_ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({"http", "https"})


def _is_valid_webhook_url(raw_url: str) -> bool:
    parsed = urlparse(raw_url)
    return parsed.scheme in _ALLOWED_URL_SCHEMES and bool(parsed.netloc)


@dataclass(kw_only=True, eq=False)
class Webhook(AggregateRoot):
    """Aggregate Root governing UCP Webhook destination configuration and lifecycle."""

    ID_PREFIX: ClassVar[str] = UcpIdPrefix.UCP_WEBHOOK.value

    id: str
    tenant_id: str
    name: str
    url: str
    auth_header_vault_ref: str | None
    active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        name: str,
        url: str,
        auth_header_vault_ref: str | None = None,
        id: str | None = None,
    ) -> Result[Webhook, UcpError]:
        if not tenant_id or not tenant_id.strip():
            return Result.fail(
                UcpValidationError.with_message("Webhook tenant_id must not be empty.")
            )
        if not name or not name.strip() or not url or not url.strip():
            return Result.fail(
                UcpValidationError.with_message(
                    "Webhook name and url must be non-empty.",
                    details={"name": name, "url": url},
                )
            )

        cleaned_url = url.strip()
        if not _is_valid_webhook_url(cleaned_url):
            return Result.fail(
                UcpValidationError.with_message(
                    "Webhook url must be a valid HTTP or HTTPS URL.",
                    details={"url": url},
                )
            )

        now = datetime.now(UTC)
        webhook_id = id or cls.new_id()

        webhook = cls(
            id=webhook_id,
            tenant_id=tenant_id.strip(),
            name=name.strip(),
            url=cleaned_url,
            auth_header_vault_ref=auth_header_vault_ref,
            active=True,
            created_at=now,
            updated_at=now,
        )
        webhook.add_domain_event(
            WebhookCreatedEvent(tenant_id=webhook.tenant_id, webhook_id=webhook_id)
        )
        return Result.ok(webhook)

    def update(
        self,
        *,
        name: str | UnsetType = UNSET,
        url: str | UnsetType = UNSET,
        active: bool | UnsetType = UNSET,
    ) -> Result[Webhook, UcpError]:
        if self.deleted_at is not None:
            return Result.fail(WebhookAlreadyDeletedError.for_id(self.id))

        new_name = resolve_unset(name, self.name)
        new_url = resolve_unset(url, self.url)
        new_active = resolve_unset(active, self.active)

        if not new_name or not new_name.strip() or not new_url or not new_url.strip():
            return Result.fail(
                UcpValidationError.with_message("Webhook name and url must be non-empty.")
            )

        cleaned_name = new_name.strip()
        cleaned_url = new_url.strip()
        if not _is_valid_webhook_url(cleaned_url):
            return Result.fail(
                UcpValidationError.with_message(
                    "Webhook url must be a valid HTTP or HTTPS URL.",
                    details={"url": cleaned_url},
                )
            )

        if cleaned_name == self.name and cleaned_url == self.url and new_active == self.active:
            return Result.ok(self)

        self.name = cleaned_name
        self.url = cleaned_url
        self.active = new_active
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(WebhookUpdatedEvent(tenant_id=self.tenant_id, webhook_id=self.id))
        return Result.ok(self)

    def mark_deleted(self) -> Result[Webhook, UcpError]:
        """Marks this webhook as deleted and records WebhookDeletedEvent internally."""
        if self.deleted_at is not None:
            return Result.fail(WebhookAlreadyDeletedError.for_id(self.id))
        now = datetime.now(UTC)
        self.active = False
        self.deleted_at = now
        self.updated_at = now
        self.add_domain_event(WebhookDeletedEvent(tenant_id=self.tenant_id, webhook_id=self.id))
        return Result.ok(self)
