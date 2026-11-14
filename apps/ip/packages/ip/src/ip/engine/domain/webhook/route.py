"""WebhookEventRoute entity for multiplexed inbound routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.webhook.enums import PayloadSemantic


@dataclass(kw_only=True, eq=False)
class WebhookEventRoute:
    """Entity representing a multiplexed routing rule on an inbound WebhookEndpoint."""

    ID_PREFIX: ClassVar[str] = IpIdPrefix.WEBHOOK_EVENT_ROUTE.value

    id: str
    endpoint_id: str
    event_pattern: str
    payload_semantic: PayloadSemantic
    target_pipeline_or_workflow_id: str
    description: str = ""
    priority: int = 100
    is_active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def matches(self, event_name: str | None) -> bool:
        """Determines if the provided event discriminator matches this route's pattern."""
        if not self.is_active:
            return False

        if self.event_pattern == "*":
            return True

        if not event_name:
            return False

        normalized_target = event_name.strip()
        normalized_pattern = self.event_pattern.strip()

        if normalized_target == normalized_pattern:
            return True

        if normalized_pattern.endswith(".*"):
            prefix = normalized_pattern[:-2]
            return normalized_target.startswith(f"{prefix}.")

        return False
