"""Pure zero-mock Phase 4 unit tests for Notification SQLAlchemy Data Mappers and Fakes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from database.models.notifications import (
    NotificationOutbox,
    NotificationRecord,
    NotificationRouteConfiguration,
    NotificationTemplate,
)
from database.models.notifications import (
    UserNotificationPreference as ORMUserNotificationPreference,
)
from database.provider import DatabaseProvider
from identity.domain.constants import IdentityIdPrefix
from seedwork.events import EventEnvelope
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import event, func, select, text

from notification.adapters.outbound.database.sqlalchemy_notification_query_repository import (
    SqlAlchemyNotificationQueryRepository,
)
from notification.adapters.outbound.database.sqlalchemy_notification_record_repository import (
    SqlAlchemyNotificationRecordRepository,
)
from notification.adapters.outbound.database.sqlalchemy_outbox_repository import (
    SqlAlchemyNotificationOutboxRepository,
)
from notification.adapters.outbound.database.sqlalchemy_route_repository import (
    SqlAlchemyNotificationRouteRepository,
)
from notification.adapters.outbound.database.sqlalchemy_template_repository import (
    SqlAlchemyTemplateRepository,
)
from notification.adapters.outbound.database.sqlalchemy_user_preference_repository import (
    SqlAlchemyUserNotificationPreferenceRepository,
)
from notification.adapters.outbound.database.uow import SqlAlchemyNotificationUnitOfWork
from notification.domain.constants import (
    NotificationIdPrefix,
    NotificationOutboxChannel,
    NotificationOutboxSource,
)
from notification.domain.dispatch import NotificationDispatch
from notification.domain.enums import Channel
from notification.domain.preference import NotificationPreference, UserNotificationPreference
from notification.domain.template import Template
from notification.testing.fakes import FakeNotificationUow, FakeOutboxRepo, FakeRecordRepo


def test_notification_repository_bidirectional_mappers_and_prefixed_ids() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    user_id = generate_id(IdentityIdPrefix.USER.value)
    idem_key = generate_id(SystemIdPrefix.IDEMPOTENCY.value)

    dispatch = NotificationDispatch.create(
        tenant_id=tenant_id,
        channel=Channel.IN_APP,
        subject="Sync Failed",
        body="Connection Salesforce failed.",
        data={"event_type": "sync.failed"},
        idempotency_key=idem_key,
    )
    record_orm = SqlAlchemyNotificationRecordRepository._to_orm_record(dispatch, user_id)
    assert record_orm.id.startswith(f"{NotificationIdPrefix.NOTIFICATION_RECORD.value}_")
    assert len(record_orm.id) == len(NotificationIdPrefix.NOTIFICATION_RECORD.value) + 1 + 32
    assert record_orm.tenant_id == tenant_id
    assert record_orm.user_id == user_id
    assert record_orm.title == "Sync Failed"
    assert record_orm.is_read is False

    assert len(dispatch.domain_events) == 1
    dispatched_outbox_orm = SqlAlchemyNotificationRecordRepository._to_outbox_orm_record(
        tenant_id, dispatch.domain_events[0]
    )
    assert dispatched_outbox_orm.id.startswith(f"{NotificationIdPrefix.NOTIFICATION_OUTBOX.value}_")
    assert (
        len(dispatched_outbox_orm.id)
        == len(NotificationIdPrefix.NOTIFICATION_OUTBOX.value) + 1 + 32
    )
    assert dispatched_outbox_orm.tenant_id == tenant_id
    assert dispatched_outbox_orm.idempotency_key == idem_key

    now = datetime.now(UTC)
    record_id = generate_id(NotificationIdPrefix.NOTIFICATION_RECORD.value)
    notif_record = NotificationRecord(
        id=record_id,
        tenant_id=tenant_id,
        user_id=user_id,
        title="Sync Failed",
        body="Connection Salesforce failed.",
        severity="error",
        is_read=False,
        created_at=now,
    )
    dto = SqlAlchemyNotificationQueryRepository._to_dto(notif_record)
    assert dto.id == record_id
    assert dto.severity == "error"
    assert dto.created_at == now.isoformat()

    # Route preference bidirectional mapper + ID generation
    route_pref = NotificationPreference(
        id="",
        tenant_id=tenant_id,
        event_type="sync.failed",
        channels=(Channel.EMAIL, Channel.IN_APP),
    )
    route_orm: NotificationRouteConfiguration = (
        SqlAlchemyNotificationRouteRepository._to_orm_record(route_pref)
    )
    assert route_orm.id.startswith(f"{NotificationIdPrefix.NOTIFICATION_ROUTE.value}_")
    assert len(route_orm.id) == len(NotificationIdPrefix.NOTIFICATION_ROUTE.value) + 1 + 32

    updated_route_pref = NotificationPreference(
        id=route_orm.id,
        tenant_id=tenant_id,
        event_type="sync.completed",
        channels=(Channel.IN_APP,),
    )
    SqlAlchemyNotificationRouteRepository._update_record_from_domain(route_orm, updated_route_pref)
    mapped_route = SqlAlchemyNotificationRouteRepository._to_domain_model(route_orm)
    assert mapped_route.id == route_orm.id
    assert mapped_route.event_type == "sync.completed"
    assert mapped_route.channels == (Channel.IN_APP,)

    # Template bidirectional mapper + ID generation
    domain_template = Template(
        id="",
        tenant_id=tenant_id,
        name="Sync Failure Email",
        event_type="sync.failed",
        channel=Channel.EMAIL,
        subject="Alert: {{conn}}",
        body_content="Body: {{conn}}",
        is_active=True,
    )
    tmpl_orm: NotificationTemplate = SqlAlchemyTemplateRepository._to_orm_record(domain_template)
    assert tmpl_orm.id.startswith(f"{NotificationIdPrefix.NOTIFICATION_TEMPLATE.value}_")
    assert len(tmpl_orm.id) == len(NotificationIdPrefix.NOTIFICATION_TEMPLATE.value) + 1 + 32

    updated_template = Template(
        id=tmpl_orm.id,
        tenant_id=tenant_id,
        name="Updated Sync Email",
        event_type="sync.failed",
        channel=Channel.EMAIL,
        subject="Updated Alert: {{conn}}",
        body_content="Updated Body: {{conn}}",
        is_active=False,
    )
    SqlAlchemyTemplateRepository._update_record_from_domain(tmpl_orm, updated_template)
    mapped_tmpl = SqlAlchemyTemplateRepository._to_domain_model(tmpl_orm)
    assert mapped_tmpl.id == tmpl_orm.id
    assert mapped_tmpl.name == "Updated Sync Email"
    assert mapped_tmpl.subject == "Updated Alert: {{conn}}"
    assert mapped_tmpl.body_content == "Updated Body: {{conn}}"
    assert mapped_tmpl.is_active is False

    # User notification preference bidirectional mapper + ID generation
    domain_user_pref = UserNotificationPreference(
        id="",
        tenant_id=tenant_id,
        user_id=user_id,
        event_type="sync.failed",
        channel=Channel.EMAIL,
        is_enabled=True,
    )
    pref_orm: ORMUserNotificationPreference = (
        SqlAlchemyUserNotificationPreferenceRepository._to_orm_record(domain_user_pref)
    )
    assert pref_orm.id.startswith(f"{NotificationIdPrefix.NOTIFICATION_PREFERENCE.value}_")

    disabled_pref = UserNotificationPreference(
        id=pref_orm.id,
        tenant_id=tenant_id,
        user_id=user_id,
        event_type="sync.failed",
        channel=Channel.EMAIL,
        is_enabled=False,
    )
    SqlAlchemyUserNotificationPreferenceRepository._update_record_from_domain(
        pref_orm, disabled_pref
    )
    mapped_user_pref = SqlAlchemyUserNotificationPreferenceRepository._to_domain_model(pref_orm)
    assert mapped_user_pref.id == pref_orm.id
    assert mapped_user_pref.channel == Channel.EMAIL
    assert mapped_user_pref.is_enabled is False

    # Notification outbox mapper
    outbox_id = generate_id(NotificationIdPrefix.NOTIFICATION_OUTBOX.value)
    envelope = EventEnvelope(
        id=outbox_id,
        source=NotificationOutboxSource.NOTIFICATION.value,
        tenant_id=tenant_id,
        event_type="email.requested",
        idempotency_key=idem_key,
        payload={"subject": "Alert"},
    )
    outbox_orm = SqlAlchemyNotificationOutboxRepository._to_orm_record(envelope)
    mapped_envelope = SqlAlchemyNotificationOutboxRepository._to_domain_model(outbox_orm)
    assert mapped_envelope.id == outbox_id
    assert mapped_envelope.source == NotificationOutboxSource.NOTIFICATION.value
    assert mapped_envelope.tenant_id == tenant_id
    assert mapped_envelope.event_type == "email.requested"
    assert mapped_envelope.payload == {"subject": "Alert"}


@pytest.mark.asyncio
async def test_notification_fakes_reflection_free_and_strictly_typed() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    idem_key = generate_id(SystemIdPrefix.IDEMPOTENCY.value)

    record_repo = FakeRecordRepo()
    outbox_repo = FakeOutboxRepo()
    uow = FakeNotificationUow(
        user_preference_repo=None,
        template_repo=None,
        record_repo=record_repo,
        route_repo=None,
        outbox_repo=outbox_repo,
    )
    dispatch = NotificationDispatch.create(
        tenant_id=tenant_id,
        channel=Channel.EMAIL,
        subject="Hello",
        body="World",
        data={"correlation": generate_id(SystemIdPrefix.GENERIC.value)},
        idempotency_key=idem_key,
    )
    await record_repo.save(dispatch)
    await uow.commit()

    assert uow.committed is True
    assert len(outbox_repo.events) == 1
    assert outbox_repo.events[0].event_type == "email.requested"


@pytest.mark.asyncio
async def test_notification_record_and_outbox_repositories_are_idempotent_on_redelivery() -> None:
    provider = DatabaseProvider.from_url("sqlite+aiosqlite:///:memory:")
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    user_id = generate_id(IdentityIdPrefix.USER.value)
    email_idem_key = generate_id(SystemIdPrefix.IDEMPOTENCY.value)
    in_app_idem_key = generate_id(SystemIdPrefix.IDEMPOTENCY.value)
    envelope_idem_key = generate_id(SystemIdPrefix.IDEMPOTENCY.value)
    pg_notifications: list[tuple[str, str]] = []

    async with provider.session_factory() as session:
        raw_conn = await session.connection()
        driver_conn = (await raw_conn.get_raw_connection()).driver_connection
        assert driver_conn is not None
        await driver_conn.create_function(
            "pg_notify",
            2,
            lambda channel, payload: pg_notifications.append((str(channel), str(payload))),
        )

        await session.execute(text("ATTACH DATABASE ':memory:' AS notifications"))
        await session.execute(
            text(
                """
                CREATE TABLE notifications.notification_outbox (
                    id VARCHAR(128) PRIMARY KEY,
                    tenant_id VARCHAR(128) NOT NULL,
                    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
                    event_type VARCHAR(100) NOT NULL,
                    trace_id VARCHAR(64) NULL,
                    correlation_id VARCHAR(255) NULL,
                    lane VARCHAR(32) NOT NULL DEFAULT 'realtime',
                    payload JSON NOT NULL,
                    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    published_at TIMESTAMP NULL,
                    error_reason VARCHAR NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    owner_token VARCHAR(128) NULL,
                    lease_expires_at TIMESTAMP NULL
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE notifications.notification_records (
                    id VARCHAR(128) PRIMARY KEY,
                    tenant_id VARCHAR(128) NOT NULL,
                    user_id VARCHAR(128) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    body VARCHAR NOT NULL,
                    severity VARCHAR(50) NOT NULL DEFAULT 'info',
                    is_read BOOLEAN NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        repo = SqlAlchemyNotificationRecordRepository(session)
        first_dispatch = NotificationDispatch.create(
            tenant_id=tenant_id,
            channel=Channel.EMAIL,
            subject="First",
            body="Body",
            data={"event_id": "evt_1"},
            idempotency_key=email_idem_key,
        )
        await repo.save(first_dispatch)
        await session.commit()

        # Redelivered EMAIL dispatch with identical idempotency_key must not raise IntegrityError
        duplicate_dispatch = NotificationDispatch.create(
            tenant_id=tenant_id,
            channel=Channel.EMAIL,
            subject="First",
            body="Body",
            data={"event_id": "evt_1"},
            idempotency_key=email_idem_key,
        )
        await repo.save(duplicate_dispatch)
        await session.commit()

        # Redelivered IN_APP dispatch must neither duplicate NotificationRecord nor re-emit pg_notify
        first_in_app = NotificationDispatch.create(
            tenant_id=tenant_id,
            channel=Channel.IN_APP,
            subject="In-App Alert",
            body="In-App Body",
            data={"user_id": user_id},
            idempotency_key=in_app_idem_key,
        )
        await repo.save(first_in_app)
        await session.commit()

        duplicate_in_app = NotificationDispatch.create(
            tenant_id=tenant_id,
            channel=Channel.IN_APP,
            subject="In-App Alert",
            body="In-App Body",
            data={"user_id": user_id},
            idempotency_key=in_app_idem_key,
        )
        await repo.save(duplicate_in_app)
        await session.commit()

        record_count = (
            await session.execute(select(func.count()).select_from(NotificationRecord))
        ).scalar_one()
        assert record_count == 1
        assert len(pg_notifications) == 1
        assert pg_notifications[0][0] == NotificationOutboxChannel.IN_APP_NOTIFICATIONS.value

        # SqlAlchemyNotificationOutboxRepository.save must also be idempotent on duplicate EventEnvelope
        outbox_repo = SqlAlchemyNotificationOutboxRepository(session)
        envelope = EventEnvelope(
            id=generate_id(NotificationIdPrefix.NOTIFICATION_OUTBOX.value),
            source=NotificationOutboxSource.NOTIFICATION.value,
            tenant_id=tenant_id,
            event_type="email.requested",
            idempotency_key=envelope_idem_key,
            payload={"subject": "Direct Outbox"},
        )
        duplicate_envelope = EventEnvelope(
            id=generate_id(NotificationIdPrefix.NOTIFICATION_OUTBOX.value),
            source=NotificationOutboxSource.NOTIFICATION.value,
            tenant_id=tenant_id,
            event_type="email.requested",
            idempotency_key=envelope_idem_key,
            payload={"subject": "Direct Outbox"},
        )
        await outbox_repo.save(envelope)
        await session.commit()
        await outbox_repo.save(duplicate_envelope)
        await session.commit()

        outbox_count = (
            await session.execute(select(func.count()).select_from(NotificationOutbox))
        ).scalar_one()
        assert outbox_count == 3

    await provider.engine.dispose()


@pytest.mark.asyncio
async def test_notification_uow_pre_commit_emits_canonical_wakeup_notify() -> None:
    assert NotificationOutboxChannel.DELIVERY_WAKEUP.value == "notification_delivery_outbox_wakeup"
    assert NotificationOutboxChannel.IN_APP_NOTIFICATIONS.value == "in_app_notifications"

    provider = DatabaseProvider.from_url("sqlite+aiosqlite:///:memory:")
    executed_statements: list[str] = []

    def _capture_do_execute(
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
    ) -> bool | None:
        del cursor, parameters, context
        executed_statements.append(statement)
        if statement.startswith("NOTIFY "):
            return True
        return None

    event.listen(provider.engine.sync_engine, "do_execute", _capture_do_execute, retval=True)
    try:
        async with provider.session_factory() as session:
            uow = SqlAlchemyNotificationUnitOfWork(
                session=session,
                user_preference_repo=SqlAlchemyUserNotificationPreferenceRepository(session),
                template_repo=SqlAlchemyTemplateRepository(session),
                record_repo=SqlAlchemyNotificationRecordRepository(session),
                route_repo=SqlAlchemyNotificationRouteRepository(session),
                outbox_repo=SqlAlchemyNotificationOutboxRepository(session),
            )
            await uow._pre_commit()
    finally:
        event.remove(provider.engine.sync_engine, "do_execute", _capture_do_execute)
        await provider.engine.dispose()

    assert executed_statements == ["NOTIFY notification_delivery_outbox_wakeup;"]
