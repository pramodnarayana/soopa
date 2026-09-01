from collections.abc import Mapping
from typing import Any

import pytest
from identity.domain.constants import IdentityIdPrefix
from seedwork.utils import generate_id
from structlog.testing import capture_logs

from notification.adapters.outbound.channels.email_delivery_strategy import (
    DeliveryError,
    EmailDeliveryStrategy,
    EmailProviderPort,
)


class FakeEmailProvider(EmailProviderPort):
    def __init__(self):
        self.sent_emails = []

    async def send_email(
        self, tenant_id: str, content: str, subject: str | None, data: Mapping[str, Any]
    ) -> None:
        self.sent_emails.append(
            {
                "tenant_id": tenant_id,
                "content": content,
                "subject": subject,
                "data": data,
            }
        )


@pytest.mark.asyncio
async def test_email_delivery_strategy_delivers():
    provider = FakeEmailProvider()
    strategy = EmailDeliveryStrategy(email_provider=provider)

    tenant_id = generate_id(IdentityIdPrefix.TENANT)
    with capture_logs() as cap_logs:
        await strategy.deliver(
            tenant_id=tenant_id,
            content="Hello",
            subject="Subj",
            data={"k": "v"},
        )

    assert len(provider.sent_emails) == 1
    assert provider.sent_emails[0]["tenant_id"] == tenant_id
    assert provider.sent_emails[0]["content"] == "Hello"

    assert any(log["event"] == "email_delivering" for log in cap_logs)


@pytest.mark.asyncio
async def test_email_delivery_strategy_fails_without_provider():
    strategy = EmailDeliveryStrategy(email_provider=None)

    tenant_id = generate_id(IdentityIdPrefix.TENANT)
    with pytest.raises(DeliveryError, match="Email provider not configured"):
        await strategy.deliver(
            tenant_id=tenant_id,
            content="Hello",
            subject="Subj",
            data={"k": "v"},
        )
