import hashlib
import logging

from ..domain.models import NotificationEvent, NotificationOutboxEvent
from ..ports.interfaces import (
    NotificationRouteRepositoryPort,
    TemplateRendererPort,
    TemplateRepositoryPort,
)
from ..ports.outbox_repository import NotificationOutboxRepositoryPort

logger = logging.getLogger(__name__)


class DispatchNotificationUseCase:
    def __init__(
        self,
        template_repo: TemplateRepositoryPort,
        template_renderer: TemplateRendererPort,
        outbox_repo: NotificationOutboxRepositoryPort,
        route_repo: NotificationRouteRepositoryPort,
    ):
        self.template_repo = template_repo
        self.template_renderer = template_renderer
        self.outbox_repo = outbox_repo
        self.route_repo = route_repo

    async def execute(self, event: NotificationEvent) -> None:
        logger.info(
            f"Dispatching notification for tenant {event.tenant_id}, event {event.event_type}"
        )

        channels = await self.route_repo.get_channels(event.tenant_id, event.event_type)
        if not channels:
            logger.info(
                f"No route configured for tenant {event.tenant_id}, event {event.event_type}. Dropping."
            )
            return

        for channel in channels:
            template = await self.template_repo.get_template(
                event.tenant_id, event.event_type, channel
            )
            if not template:
                logger.warning(
                    f"No template found for tenant {event.tenant_id}, event {event.event_type}, channel {channel.value}"
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
