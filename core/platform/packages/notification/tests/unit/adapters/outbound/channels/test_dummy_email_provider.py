import pytest
from structlog.testing import capture_logs

from notification.adapters.outbound.channels.dummy_email_provider import DummyEmailProvider


@pytest.mark.asyncio
async def test_dummy_email_provider():
    provider = DummyEmailProvider()
    with capture_logs() as cap_logs:
        await provider.send_email(
            tenant_id="ten_123",
            content="Hello World",
            subject="Welcome",
            data={"foo": "bar"},
        )

    assert len(cap_logs) == 1
    assert cap_logs[0]["event"] == "dummy_email_sent"
    assert cap_logs[0]["tenant_id"] == "ten_123"
