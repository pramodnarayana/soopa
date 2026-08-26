import hashlib
from typing import Any

import structlog
from platform_orm.events import EventEnvelope

from notification.ports.outbound.notification_outbox_repository_port import (
    NotificationOutboxRepositoryPort,
)

from ..domain.models import PLATFORM_TENANT_ID, NotificationEvent
from ..ports.outbound.notification_record_repository_port import NotificationRecordRepositoryPort
from ..ports.outbound.notification_route_repository_port import NotificationRouteRepositoryPort
from ..ports.outbound.template_renderer_port import TemplateRendererPort
from ..ports.outbound.template_repository_port import TemplateRepositoryPort
from ..ports.outbound.user_notification_preference_repository_port import (
    UserNotificationPreferenceRepositoryPort,
)

logger = structlog.get_logger(__name__)


class NotificationCompilerUseCase:
    def __init__(
        self,
        template_repo: TemplateRepositoryPort,
        template_renderer: TemplateRendererPort,
        outbox_repo: NotificationOutboxRepositoryPort,
        route_repo: NotificationRouteRepositoryPort,
        user_pref_repo: UserNotificationPreferenceRepositoryPort,
        record_repo: NotificationRecordRepositoryPort,
    ):
        self.template_repo = template_repo
        self.template_renderer = template_renderer
        self.outbox_repo = outbox_repo
        self.route_repo = route_repo
        self.user_pref_repo = user_pref_repo
        self.record_repo = record_repo

    async def execute(self, event: NotificationEvent) -> None:
        bound_logger = logger.bind(
            tenant_id=event.tenant_id,
            event_type=event.event_type,
            user_id=event.data.get("user_id"),
        )
        bound_logger.info("notification_compiler.started")

        channels = await self.route_repo.get_channels(event.tenant_id, event.event_type)
        if not channels:
            # Fallback to platform-level default channels if tenant has no specific config
            channels = await self.route_repo.get_channels(PLATFORM_TENANT_ID, event.event_type)
            if not channels:
                bound_logger.info("notification_compiler.dropped_no_route")
                return

        for channel in channels:
            # Check user-level preferences if this is a user-specific event
            user_id = event.data.get("user_id")
            if user_id:
                pref = await self.user_pref_repo.get_preference(
                    tenant_id=event.tenant_id,
                    user_id=user_id,
                    event_type=event.event_type,
                    channel=channel.value,
                )
                # Default is opt-out: meaning they receive it unless they explicitly disabled it
                if pref is not None and not pref.is_enabled:
                    bound_logger.info(
                        "notification_compiler.skipped_user_opt_out", channel=channel.value
                    )
                    continue
            template = await self.template_repo.get_template(
                event.tenant_id, event.event_type, channel
            )
            if not template:
                bound_logger.warning(
                    "notification_compiler.missing_template", channel=channel.value
                )
                continue

            # Stage 2: Heavy Lifting - Rendering the Template
            rendered_body = self.template_renderer.render(template.body_content, event.data)
            rendered_subject = (
                self.template_renderer.render(template.subject, event.data)
                if template.subject
                else None
            )

            # Generate deterministic idempotency key
            event_id = event.data.get("event_id", "")
            idempotency_input = f"{event.tenant_id}:{event.event_type}:{channel.value}:{event_id}"
            idempotency_key = hashlib.sha256(idempotency_input.encode()).hexdigest()

            # The Dual Write (History Ledger + Dispatch Outbox)
            # 1. Save History
            await self.record_repo.save_notification(
                tenant_id=event.tenant_id,
                content=rendered_body,
                subject=rendered_subject,
                data=dict(event.data),
            )

            # 2. Insert Outbox Dispatch Event (e.g., "email.requested")
            dispatch_event_type = f"{channel.value}.requested"

            payload: dict[str, Any] = {
                "channel": channel.value,
                "content": rendered_body,
                "subject": rendered_subject,
                "data": event.data,
            }

            import uuid

            outbox_event = EventEnvelope(
                id=str(uuid.uuid4()),
                source="notification",
                tenant_id=event.tenant_id,
                event_type=dispatch_event_type,
                idempotency_key=idempotency_key,
                payload=payload,
            )
            await self.outbox_repo.save(outbox_event)

            bound_logger.info(
                "notification_compiler.completed",
                channel=channel.value,
                outbox_event_id=idempotency_key,
            )
