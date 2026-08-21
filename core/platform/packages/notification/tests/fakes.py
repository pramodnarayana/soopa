from notification.domain.models import (
    Channel,
    NotificationOutboxEvent,
    Template,
    UserNotificationPreference,
)
from notification.ports.outbound.notification_outbox_repository_port import (
    NotificationOutboxRepositoryPort,
)
from notification.ports.outbound.notification_route_repository_port import (
    NotificationRouteRepositoryPort,
)
from notification.ports.outbound.template_renderer_port import TemplateRendererPort
from notification.ports.outbound.template_repository_port import TemplateRepositoryPort
from notification.ports.outbound.user_notification_preference_repository_port import (
    UserNotificationPreferenceRepositoryPort,
)


class FakeUserPrefRepo(UserNotificationPreferenceRepositoryPort):
    def __init__(self):
        self.prefs = {}

    async def get_preference(
        self, tenant_id: str, user_id: str, event_type: str, channel: str
    ) -> UserNotificationPreference | None:
        return self.prefs.get((tenant_id, user_id, event_type, channel))

    async def get_user_preferences(
        self, tenant_id: str, user_id: str
    ) -> list[UserNotificationPreference]:
        return [p for p in self.prefs.values() if p.tenant_id == tenant_id and p.user_id == user_id]

    async def save_preference(self, preference: UserNotificationPreference) -> None:
        key = (
            preference.tenant_id,
            preference.user_id,
            preference.event_type,
            preference.channel.value,
        )
        if key in self.prefs:
            existing = self.prefs[key]
            import dataclasses

            # Preserve existing ID by creating a new instance
            preference = dataclasses.replace(preference, id=existing.id)

        self.prefs[key] = preference


class FakeTemplateRepo(TemplateRepositoryPort):
    def __init__(self):
        self.templates = {}

    async def get_template(
        self, tenant_id: str, event_type: str, channel: Channel
    ) -> Template | None:
        return self.templates.get((tenant_id, event_type, channel))


class FakeTemplateRenderer(TemplateRendererPort):
    def render(self, template_str: str, context: dict) -> str:
        result = template_str
        for k, v in context.items():
            result = result.replace(f"{{{{{k}}}}}", str(v))
        return result


class FakeOutboxRepo(NotificationOutboxRepositoryPort):
    def __init__(self):
        self.events = []
        self.stuck_swept = 0
        self.next_messages = []
        self.completed = []
        self.failed = []

    async def save(self, event: NotificationOutboxEvent) -> None:
        self.events.append(event)

    async def sweep_stuck_messages(self, lock_lease_ms: int) -> int:
        return self.stuck_swept

    async def claim_next_messages(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[NotificationOutboxEvent]:
        return self.next_messages[:limit]

    async def mark_completed(self, message_id: str, worker_id: str) -> None:
        self.completed.append((message_id, worker_id))

    async def mark_failed(self, message_id: str, worker_id: str, error_reason: str) -> None:
        self.failed.append((message_id, worker_id, error_reason))


class FakeRouteRepo(NotificationRouteRepositoryPort):
    def __init__(self):
        self.routes = {}

    async def get_channels(self, tenant_id: str, event_type: str) -> list[Channel]:
        return self.routes.get((tenant_id, event_type), [])
