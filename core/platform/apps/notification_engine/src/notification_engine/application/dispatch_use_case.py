import logging

from ..domain.models import NotificationEvent
from ..ports.interfaces import DeliveryDispatcherPort, TemplateRendererPort, TemplateRepositoryPort

logger = logging.getLogger(__name__)


class DispatchNotificationUseCase:
    def __init__(
        self,
        template_repo: TemplateRepositoryPort,
        template_renderer: TemplateRendererPort,
        dispatcher: DeliveryDispatcherPort,
    ):
        self.template_repo = template_repo
        self.template_renderer = template_renderer
        self.dispatcher = dispatcher

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

            await self.dispatcher.dispatch(
                channel=channel,
                tenant_id=event.tenant_id,
                content=rendered_body,
                subject=rendered_subject,
                data=event.data,
            )
