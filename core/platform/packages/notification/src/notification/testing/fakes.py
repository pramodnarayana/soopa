from collections.abc import Mapping
from typing import Any

from database.events import EventEnvelope

from notification.domain.models import (
    Channel,
    NotificationDispatch,
    Template,
    UserNotificationPreference,
)
from notification.ports.outbound.notification_outbox_repository_port import (
    NotificationOutboxRepositoryPort,
)
from notification.ports.outbound.notification_record_repository_port import (
    NotificationRecordRepositoryPort,
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
    def __init__(self) -> None:
        self.prefs: dict[Any, Any] = {}

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
    def __init__(self) -> None:
        self.templates: dict[Any, Any] = {}

    async def get_template(
        self, tenant_id: str, event_type: str, channel: Channel
    ) -> Template | None:
        return self.templates.get((tenant_id, event_type, channel))


class FakeTemplateRenderer(TemplateRendererPort):
    def render(self, template_str: str, context: Mapping[str, Any]) -> str:
        result = template_str
        for k, v in context.items():
            result = result.replace(f"{{{{{k}}}}}", str(v))
        return result


class FakeOutboxRepo(NotificationOutboxRepositoryPort):
    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []
        self.stuck_swept = 0
        self.next_messages: list[EventEnvelope] = []
        self.completed: list[Any] = []
        self.failed: list[Any] = []

    async def save(self, event: EventEnvelope) -> None:
        self.events.append(event)

    async def sweep_stuck_messages(self, lock_lease_ms: int) -> int:
        return self.stuck_swept

    async def claim_next_messages(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[EventEnvelope]:
        return self.next_messages[:limit]

    async def mark_completed(self, message_id: str, worker_id: str) -> None:
        self.completed.append((message_id, worker_id))

    async def mark_failed(self, message_id: str, worker_id: str, error_reason: str) -> None:
        self.failed.append((message_id, worker_id, error_reason))


class FakeRouteRepo(NotificationRouteRepositoryPort):
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], list[Channel]] = {}

    async def get_channels(self, tenant_id: str, event_type: str) -> list[Channel]:
        return self.routes.get((tenant_id, event_type), [])


class FakeRecordRepo(NotificationRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: list[Any] = []
        self.dispatches: list[NotificationDispatch] = []

    async def save(self, dispatch: NotificationDispatch) -> None:
        from notification.domain.models import Channel

        self.dispatches.append(dispatch)
        if dispatch.channel == Channel.IN_APP:
            self.records.append(
                (dispatch.tenant_id, dispatch.body, dispatch.subject, dispatch.data)
            )


from notification.ports.outbound.uow_port import NotificationUnitOfWorkPort


class FakeNotificationUow(NotificationUnitOfWorkPort):
    def __init__(
        self,
        user_preference_repo: Any,
        template_repo: Any,
        record_repo: Any,
        route_repo: Any,
        outbox_repo: Any,
    ) -> None:
        self.user_preference_repo = user_preference_repo
        self.template_repo = template_repo
        self.record_repo = record_repo
        self.route_repo = route_repo
        self.outbox_repo = outbox_repo
        self.committed = False
        self.rolled_back = False

    async def _pre_commit(self) -> None:
        pass

    async def commit(self) -> None:
        await self._pre_commit()
        # Simulate Outbox event collection
        if self.record_repo and hasattr(self.record_repo, "dispatches"):
            import dataclasses
            import uuid

            for dispatch in self.record_repo.dispatches:
                for event in dispatch.domain_events:
                    outbox_event = EventEnvelope(
                        id=str(uuid.uuid4()),
                        source="notification",
                        tenant_id=event.tenant_id,
                        event_type=event.event_name,
                        idempotency_key=event.idempotency_key,
                        payload=dataclasses.asdict(event),
                    )
                    await self.outbox_repo.save(outbox_event)
                dispatch.clear_domain_events()
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def __aenter__(self) -> "FakeNotificationUow":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass
