import hashlib
import logging
import os

from ucp_models.notifications import NotificationOutbox

from ..domain.models import NotificationEvent
from ..ports.interfaces import TemplateRendererPort, TemplateRepositoryPort
from ..ports.outbox_repository import NotificationOutboxRepositoryPort

logger = logging.getLogger(__name__)


class DispatchNotificationUseCase:
    def __init__(
        self,
        template_repo: TemplateRepositoryPort,
        template_renderer: TemplateRendererPort,
        outbox_repo: NotificationOutboxRepositoryPort,
    ):
        self.template_repo = template_repo
        self.template_renderer = template_renderer
        self.outbox_repo = outbox_repo

    async def execute(self, event: NotificationEvent) -> None:
        logger.info(
            f"Dispatching notification for tenant {event.tenant_id}, event {event.event_type}"
        )

        for channel in event.channels:
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

            outbox_msg = NotificationOutbox(
                id=f"{NotificationOutbox.ID_PREFIX}_{os.urandom(12).hex()}",
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
            await self.outbox_repo.save(outbox_msg)
