import pytest

from edi_delivery_worker.adapters.acl.registry import UcpEventNames, translate_external_event
from edi_delivery_worker.adapters.acl.ucp_translators import WebhookEventTranslator


def test_webhook_event_translator_success() -> None:
    translator = WebhookEventTranslator(UcpEventNames.WEBHOOK_CREATED)
    payload = {"tenantId": "t1", "webhook_id": "wh1"}
    res = translator.translate(payload)
    assert res == {
        "event_type": UcpEventNames.WEBHOOK_CREATED,
        "payload": {"tenant_id": "t1", "resource_id": "wh1"},
    }


def test_webhook_event_translator_missing_tenant() -> None:
    translator = WebhookEventTranslator(UcpEventNames.WEBHOOK_CREATED)
    with pytest.raises(ValueError, match="tenant identifier not found"):
        translator.translate({"webhook_id": "wh1"})


def test_webhook_event_translator_not_dict() -> None:
    translator = WebhookEventTranslator(UcpEventNames.WEBHOOK_CREATED)
    with pytest.raises(TypeError, match="must be a mapping"):
        translator.translate("not_a_dict")  # type: ignore[arg-type]


def test_registry_translate_external_event_found() -> None:
    payload = {"tenantId": "t2", "webhook_id": "wh2"}
    res = translate_external_event(UcpEventNames.WEBHOOK_UPDATED, payload)
    assert res == {
        "event_type": UcpEventNames.WEBHOOK_UPDATED,
        "payload": {"tenant_id": "t2", "resource_id": "wh2"},
    }


def test_registry_translate_external_event_not_found() -> None:
    res = translate_external_event("unknown.event", {"tenantId": "t2"})
    assert res is None


def test_registry_translate_external_event_exception() -> None:
    with pytest.raises(ValueError):
        translate_external_event(UcpEventNames.WEBHOOK_DELETED, {"webhook_id": "wh1"})
