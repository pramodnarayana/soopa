import httpx
import pytest
from database.models.identity import User as UserORM
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_get_notifications(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]
    user_id = "usr_platform_admin_123"
    response = await auth_client.get(f"/api/v1/notifications/{tenant_id}/users/{user_id}/in-app")
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_mark_notification_read(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]
    user_id = "usr_platform_admin_123"
    response = await auth_client.put(
        f"/api/v1/notifications/{tenant_id}/users/{user_id}/in-app/notif_123/read"
    )
    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_notification_templates_preferences_and_user_preferences_lifecycle(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]
    user_id = "usr_platform_admin_123"

    async with db_session_factory() as session:
        existing_user = await session.get(UserORM, user_id)
        if existing_user is None:
            session.add(
                UserORM(
                    id=user_id,
                    email="platform.admin@example.com",
                    name="Platform Admin",
                    status="active",
                )
            )
            await session.commit()

    # 1. Templates CRUD + Preview
    tpl_base = f"/api/v1/notifications/{tenant_id}/templates"
    forbidden_tpl = await auth_client.get("/api/v1/notifications/ten_unauthorized_999/templates")
    assert forbidden_tpl.status_code == 403

    upsert_tpl = await auth_client.put(
        tpl_base,
        json={
            "name": "Order Dispatched Email",
            "event_type": "order.dispatched",
            "channel": "EMAIL",
            "subject_template": "Order {{ order_id }} Dispatched",
            "body_template": "Hello {{ customer_name }}, order {{ order_id }} shipped.",
            "is_active": True,
        },
    )
    assert upsert_tpl.status_code == 200, upsert_tpl.text
    template_id = upsert_tpl.json()["id"]

    list_tpl = await auth_client.get(tpl_base)
    assert list_tpl.status_code == 200
    assert any(t["id"] == template_id for t in list_tpl.json())

    invalid_tpl = await auth_client.put(
        tpl_base,
        json={
            "name": "   ",
            "event_type": "order.dispatched",
            "channel": "UNSUPPORTED_CHANNEL",
            "body_template": "   ",
        },
    )
    assert invalid_tpl.status_code == 422

    preview_ok = await auth_client.post(
        f"{tpl_base}/preview",
        json={
            "subject_template": "Order {{ order_id }}",
            "body_template": "Hi {{ customer_name }}!",
            "fake_payload": {"order_id": "ORD-42", "customer_name": "Alice"},
        },
    )
    assert preview_ok.status_code == 200
    assert preview_ok.json()["rendered_subject"] == "Order ORD-42"
    assert preview_ok.json()["rendered_body"] == "Hi Alice!"

    preview_body_too_big = await auth_client.post(
        f"{tpl_base}/preview",
        json={"body_template": "x" * 10_001, "fake_payload": {}},
    )
    assert preview_body_too_big.status_code == 400

    preview_subject_too_big = await auth_client.post(
        f"{tpl_base}/preview",
        json={
            "subject_template": "s" * 10_001,
            "body_template": "Hi",
            "fake_payload": {},
        },
    )
    assert preview_subject_too_big.status_code == 400

    preview_payload_too_big = await auth_client.post(
        f"{tpl_base}/preview",
        json={
            "body_template": "Hi",
            "fake_payload": {"blob": "p" * 50_005},
        },
    )
    assert preview_payload_too_big.status_code == 400

    preview_syntax_err = await auth_client.post(
        f"{tpl_base}/preview",
        json={
            "body_template": "Broken {{ unclosed_var",
            "fake_payload": {},
        },
    )
    assert preview_syntax_err.status_code == 400

    del_tpl = await auth_client.delete(f"{tpl_base}/{template_id}")
    assert del_tpl.status_code == 204

    del_tpl_missing = await auth_client.delete(f"{tpl_base}/{template_id}")
    assert del_tpl_missing.status_code == 404

    # 2. Tenant Routing Preferences CRUD
    pref_base = f"/api/v1/notifications/{tenant_id}/preferences"
    upsert_pref = await auth_client.put(
        f"{pref_base}/order.dispatched",
        json={"channels": ["EMAIL", "IN_APP"]},
    )
    assert upsert_pref.status_code == 200, upsert_pref.text
    assert set(upsert_pref.json()["channels"]) == {"EMAIL", "IN_APP"}

    list_pref = await auth_client.get(pref_base)
    assert list_pref.status_code == 200
    assert any(p["event_type"] == "order.dispatched" for p in list_pref.json())

    invalid_pref = await auth_client.put(
        f"{pref_base}/order.dispatched",
        json={"channels": []},
    )
    assert invalid_pref.status_code == 422

    del_pref = await auth_client.delete(f"{pref_base}/order.dispatched")
    assert del_pref.status_code == 204

    del_pref_missing = await auth_client.delete(f"{pref_base}/order.dispatched")
    assert del_pref_missing.status_code == 404

    # 3. User Notification Preferences
    user_pref_url = f"/api/v1/users/{tenant_id}/{user_id}/notification-preferences"
    patch_user_pref = await auth_client.patch(
        f"{user_pref_url}/order.dispatched/EMAIL",
        json={"is_enabled": False},
    )
    assert patch_user_pref.status_code == 200, patch_user_pref.text
    assert patch_user_pref.json()["is_enabled"] is False

    get_user_prefs = await auth_client.get(user_pref_url)
    assert get_user_prefs.status_code == 200
    assert any(p["event_type"] == "order.dispatched" for p in get_user_prefs.json())

    forbidden_user_prefs = await auth_client.get(
        f"/api/v1/users/{tenant_id}/usr_another_person/notification-preferences"
    )
    assert forbidden_user_prefs.status_code == 403


@pytest.mark.asyncio
async def test_api_tokens_crud_lifecycle(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]
    tokens_url = f"/api/v1/tenants/{tenant_id}/tokens"

    create_res = await auth_client.post(tokens_url, json={"name": "Automation M2M Token"})
    assert create_res.status_code == 201, create_res.text
    created = create_res.json()
    token_id = created["id"]
    assert created["token"].startswith("sp_api_")

    list_res = await auth_client.get(tokens_url)
    assert list_res.status_code == 200
    assert any(t["id"] == token_id for t in list_res.json())

    patch_res = await auth_client.patch(
        f"{tokens_url}/{token_id}",
        json={"name": "Rotated M2M Token", "active": False},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == "Rotated M2M Token"
    assert patch_res.json()["active"] is False

    del_res = await auth_client.delete(f"{tokens_url}/{token_id}")
    assert del_res.status_code == 204

    del_missing = await auth_client.delete(f"{tokens_url}/{token_id}")
    assert del_missing.status_code == 404

    webhooks_url = f"/api/v1/tenants/{tenant_id}/webhooks"
    wh_create = await auth_client.post(
        webhooks_url,
        json={"name": "Lifecycle Webhook", "url": "https://example.com/hook"},
    )
    assert wh_create.status_code == 201, wh_create.text
    wh_id = wh_create.json()["id"]

    wh_patch = await auth_client.patch(
        f"{webhooks_url}/{wh_id}",
        json={"name": "Updated Webhook", "url": "https://example.com/hook-v2", "active": False},
    )
    assert wh_patch.status_code == 200
    assert wh_patch.json()["name"] == "Updated Webhook"

    wh_patch_missing = await auth_client.patch(
        f"{webhooks_url}/wh_missing_999",
        json={"name": "Missing Webhook"},
    )
    assert wh_patch_missing.status_code == 404

    wh_del = await auth_client.delete(f"{webhooks_url}/{wh_id}")
    assert wh_del.status_code == 204

    wh_del_missing = await auth_client.delete(f"{webhooks_url}/wh_missing_999")
    assert wh_del_missing.status_code == 404
