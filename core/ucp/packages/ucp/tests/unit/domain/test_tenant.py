from datetime import datetime

from seedwork.utils import generate_id

from ucp.domain.constants import LifecycleStatus, UcpEventType
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.domain.events import (
    AppSubscribedEvent,
    AppUnsubscribedEvent,
    TenantDeletedEvent,
    TenantNameUpdatedEvent,
    TenantStatusToggledEvent,
    WebhookDeletedEvent,
    WebhookUpdatedEvent,
)
from ucp.domain.exceptions import UcpErrorCode
from ucp.domain.tenant import Tenant
from ucp.domain.webhook import Webhook


def test_tenant_create_validates_name_and_slug() -> None:
    empty_name = Tenant.create(
        id=generate_id(DomainIdPrefix.TENANT),
        name="   ",
        slug="valid-slug",
        idp_tenant_id=None,
    )
    assert empty_name.is_err
    assert empty_name.unwrap_err().code == UcpErrorCode.EMPTY_TENANT_NAME

    empty_slug = Tenant.create(
        id=generate_id(DomainIdPrefix.TENANT),
        name="Valid Name",
        slug="   ",
        idp_tenant_id=None,
    )
    assert empty_slug.is_err
    assert empty_slug.unwrap_err().code == UcpErrorCode.INVALID_TENANT_NAME


def test_tenant_mark_deleted_success() -> None:
    tenant = Tenant.create(
        id=generate_id(DomainIdPrefix.TENANT),
        name="Test",
        slug="test",
        idp_tenant_id="org_123",
    ).unwrap()
    assert tenant.deleted_at is None

    res = tenant.mark_deleted()

    assert res.is_ok
    assert tenant.deleted_at is not None
    assert isinstance(tenant.deleted_at, datetime)
    assert len(tenant.domain_events) == 2
    assert isinstance(tenant.domain_events[-1], TenantDeletedEvent)
    assert tenant.domain_events[-1].event_name == UcpEventType.TENANT_DELETED.value


def test_tenant_mark_deleted_already_deleted() -> None:
    tenant = Tenant.create(
        id=generate_id(DomainIdPrefix.TENANT),
        name="Test",
        slug="test",
        idp_tenant_id="org_123",
    ).unwrap()
    assert tenant.mark_deleted().is_ok

    second = tenant.mark_deleted()
    assert second.is_err
    assert second.unwrap_err().code == UcpErrorCode.TENANT_ALREADY_DELETED


def test_tenant_rename_set_idp_subscribe_unsubscribe_and_status_results() -> None:
    tenant = Tenant.create(
        id=generate_id(DomainIdPrefix.TENANT),
        name="Initial",
        slug="initial",
        idp_tenant_id=None,
    ).unwrap()
    tenant.clear_domain_events()

    assert tenant.set_idp_tenant_id("org_1").is_ok
    assert tenant.set_idp_tenant_id("org_1").is_ok
    conflict = tenant.set_idp_tenant_id("org_2")
    assert conflict.is_err
    assert conflict.unwrap_err().code == UcpErrorCode.IDP_ORGANIZATION_CONFLICT

    empty_rename = tenant.rename("   ")
    assert empty_rename.is_err
    assert empty_rename.unwrap_err().code == UcpErrorCode.EMPTY_TENANT_NAME

    rename_ok = tenant.rename("  Acme Corp ")
    assert rename_ok.is_ok
    assert tenant.name == "Acme Corp"
    assert isinstance(tenant.domain_events[-1], TenantNameUpdatedEvent)

    tenant.clear_domain_events()
    noop_rename = tenant.rename("Acme Corp")
    assert noop_rename.is_ok
    assert len(tenant.domain_events) == 0

    sub_ok = tenant.subscribe("app_edi", "proj_1")
    assert sub_ok.is_ok
    assert isinstance(tenant.domain_events[-1], AppSubscribedEvent)

    dup_sub = tenant.subscribe("app_edi", "proj_1")
    assert dup_sub.is_err
    assert dup_sub.unwrap_err().code == UcpErrorCode.APP_ALREADY_SUBSCRIBED

    unsub_ok = tenant.unsubscribe_from_app("app_edi", "proj_1")
    assert unsub_ok.is_ok
    assert isinstance(tenant.domain_events[-1], AppUnsubscribedEvent)

    unsub_missing = tenant.unsubscribe_from_app("app_edi", "proj_1")
    assert unsub_missing.is_err
    assert unsub_missing.unwrap_err().code == UcpErrorCode.APP_NOT_SUBSCRIBED

    status_ok = tenant.change_status(LifecycleStatus.INACTIVE)
    assert status_ok.is_ok
    assert isinstance(tenant.domain_events[-1], TenantStatusToggledEvent)

    inactive_sub = tenant.subscribe("app_ip", "proj_2")
    assert inactive_sub.is_err
    assert inactive_sub.unwrap_err().code == UcpErrorCode.TENANT_INACTIVE_FOR_SUBSCRIPTION


def test_webhook_lifecycle_and_validation() -> None:
    tenant_id = generate_id(DomainIdPrefix.TENANT)

    bad_url = Webhook.create(
        tenant_id=tenant_id,
        name="Orders Hook",
        url="ftp://hooks.example.com/orders",
        auth_header_vault_ref=None,
    )
    assert bad_url.is_err
    assert bad_url.unwrap_err().code == UcpErrorCode.VALIDATION_FAILED

    webhook = Webhook.create(
        tenant_id=tenant_id,
        name="Orders Hook",
        url="https://hooks.example.com/orders",
        auth_header_vault_ref=None,
    ).unwrap()
    webhook.clear_domain_events()

    noop_update = webhook.update()
    assert noop_update.is_ok
    assert len(webhook.domain_events) == 0

    upd = webhook.update(name="Updated Orders Hook")
    assert upd.is_ok
    assert webhook.name == "Updated Orders Hook"
    assert len(webhook.domain_events) == 1
    assert isinstance(webhook.domain_events[0], WebhookUpdatedEvent)
    webhook.clear_domain_events()

    del_res = webhook.mark_deleted()
    assert del_res.is_ok
    assert webhook.active is False
    assert len(webhook.domain_events) == 1
    assert isinstance(webhook.domain_events[0], WebhookDeletedEvent)

    second_del = webhook.mark_deleted()
    assert second_del.is_err
    assert second_del.unwrap_err().code == UcpErrorCode.WEBHOOK_ALREADY_DELETED
