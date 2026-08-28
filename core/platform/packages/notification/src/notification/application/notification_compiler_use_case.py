import hashlib

import structlog

from ..domain.models import PLATFORM_TENANT_ID, NotificationDispatch, NotificationEvent
from ..ports.outbound.template_renderer_port import TemplateRendererPort
from ..ports.outbound.uow_port import NotificationUnitOfWorkPort

logger = structlog.get_logger(__name__)


class NotificationCompilerUseCase:
    def __init__(
        self,
        uow: NotificationUnitOfWorkPort,
        template_renderer: TemplateRendererPort,
    ):
        self.uow = uow
        self.template_renderer = template_renderer

    async def execute(self, event: NotificationEvent) -> None:
        bound_logger = logger.bind(
            tenant_id=event.tenant_id,
            event_type=event.event_type,
            user_id=event.data.get("user_id"),
        )
        bound_logger.info("notification_compiler.started")

        channels = await self.uow.route_repo.get_channels(event.tenant_id, event.event_type)
        if not channels:
            # Fallback to platform-level default channels if tenant has no specific config
            channels = await self.uow.route_repo.get_channels(PLATFORM_TENANT_ID, event.event_type)
            if not channels:
                bound_logger.info("notification_compiler.dropped_no_route")
                return

        for channel in channels:
            # Check user-level preferences if this is a user-specific event
            user_id = event.data.get("user_id")
            if user_id:
                pref = await self.uow.user_preference_repo.get_preference(
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
            template = await self.uow.template_repo.get_template(
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

            async with self.uow:
                dispatch = NotificationDispatch.create(
                    tenant_id=event.tenant_id,
                    channel=channel,
                    subject=rendered_subject,
                    body=rendered_body,
                    data=dict(event.data),
                    idempotency_key=idempotency_key,
                )
                await self.uow.record_repo.save(dispatch)
                await self.uow.commit()

            bound_logger.info(
                "notification_compiler.completed",
                channel=channel.value,
                outbox_event_id=idempotency_key,
            )
