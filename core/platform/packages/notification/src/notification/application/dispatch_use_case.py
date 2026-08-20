import hashlib

import structlog

from ..adapters.outbound.postgres_template_repository import PLATFORM_TENANT_ID
from ..domain.models import NotificationEvent, NotificationOutboxEvent

# (
from ..ports.notification_outbox_repository_port import NotificationOutboxRepositoryPort
from ..ports.notification_route_repository_port import NotificationRouteRepositoryPort
from ..ports.template_renderer_port import TemplateRendererPort
from ..ports.template_repository_port import TemplateRepositoryPort
from ..ports.user_notification_preference_repository_port import (
    UserNotificationPreferenceRepositoryPort,
)

logger = structlog.get_logger(__name__)


class DispatchNotificationUseCase:
    def __init__(
        self,
        template_repo: TemplateRepositoryPort,
        template_renderer: TemplateRendererPort,
        outbox_repo: NotificationOutboxRepositoryPort,
        route_repo: NotificationRouteRepositoryPort,
        user_pref_repo: UserNotificationPreferenceRepositoryPort,
    ):
        self.template_repo = template_repo
        self.template_renderer = template_renderer
        self.outbox_repo = outbox_repo
        self.route_repo = route_repo
        self.user_pref_repo = user_pref_repo

    async def execute(self, event: NotificationEvent) -> None:
        bound_logger = logger.bind(
            tenant_id=event.tenant_id,
            event_type=event.event_type,
            user_id=event.data.get("user_id"),
        )
        bound_logger.info("notification_dispatch.started")

        channels = await self.route_repo.get_channels(event.tenant_id, event.event_type)
        if not channels:
            # Fallback to platform-level default channels if tenant has no specific config
            channels = await self.route_repo.get_channels(PLATFORM_TENANT_ID, event.event_type)
            if not channels:
                bound_logger.info("notification_dispatch.dropped_no_route")
                # TODO: Emit metric for dropped notifications (e.g., metrics.increment("notifications.dropped"))
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
                        "notification_dispatch.skipped_user_opt_out", channel=channel.value
                    )
                    continue
            template = await self.template_repo.get_template(
                event.tenant_id, event.event_type, channel
            )
            if not template:
                bound_logger.warning(
                    "notification_dispatch.missing_template", channel=channel.value
                )
                continue

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

            outbox_event = NotificationOutboxEvent(
                tenant_id=event.tenant_id,
                event_type=event.event_type,
                idempotency_key=idempotency_key,
                payload={
                    "channel": channel.value,
                    "content": rendered_body,
                    "subject": rendered_subject,
                    "data": event.data,
                },
            )
            await self.outbox_repo.save(outbox_event)
            bound_logger.info(
                "notification_dispatch.outbox_saved",
                channel=channel.value,
                outbox_event_id=idempotency_key,
            )
