from typing import Any, Protocol

from ..domain.models import Channel, NotificationPreference, Template, UserNotificationPreference


class TemplateRepositoryPort(Protocol):
    async def get_template(
        self, tenant_id: str, event_type: str, channel: Channel
    ) -> Template | None: ...


class NotificationRouteRepositoryPort(Protocol):
    async def get_channels(self, tenant_id: str, event_type: str) -> list[Channel]: ...


class TemplateRendererPort(Protocol):
    def render(self, template_str: str, data: dict[str, Any]) -> str: ...


class DeliveryStrategyPort(Protocol):
    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None: ...


class DeliveryDispatcherPort(Protocol):
    async def dispatch(
        self,
        channel: Channel,
        tenant_id: str,
        content: str,
        subject: str | None,
        data: dict[str, Any],
    ) -> None: ...


class NotificationPreferencesRepositoryPort(Protocol):
    """Port for reading and writing tenant notification routing rules."""

    async def list_preferences(self, tenant_id: str) -> list[NotificationPreference]: ...

    async def upsert_preference(
        self,
        tenant_id: str,
        event_type: str,
        channels: list[str],
    ) -> NotificationPreference: ...

    async def delete_preference(self, tenant_id: str, event_type: str) -> bool: ...


class NotificationTemplatesRepositoryPort(Protocol):
    """Port for reading and writing tenant Jinja2 notification templates."""

    async def list_templates(self, tenant_id: str) -> list[Template]: ...

    async def upsert_template(
        self,
        tenant_id: str,
        name: str,
        event_type: str,
        channel: str,
        subject_template: str | None,
        body_template: str,
        is_active: bool,
    ) -> Template: ...

    async def delete_template(self, tenant_id: str, template_id: str) -> bool: ...


class UserNotificationPreferenceRepositoryPort(Protocol):
    """Port for fetching and updating user notification preferences."""

    async def get_preference(
        self, tenant_id: str, user_id: str, event_type: str, channel: str
    ) -> UserNotificationPreference | None: ...

    async def get_user_preferences(
        self, tenant_id: str, user_id: str
    ) -> list[UserNotificationPreference]: ...

    async def save_preference(self, preference: UserNotificationPreference) -> None: ...
