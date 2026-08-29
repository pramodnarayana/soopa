"""
Unit tests for AwsSqsConsumer.

All aioboto3 I/O is mocked at the session/client level — this is appropriate
because aioboto3 is an external infrastructure dependency, not our domain logic.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.message import AckableMessage

QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789/test-queue"


def _make_sqs_client(messages: list[dict] | None = None) -> AsyncMock:
    """Builds a fully-configured mock SQS client."""
    client = AsyncMock()
    client.receive_message.return_value = {"Messages": messages or []}
    client.delete_message.return_value = {}
    return client


def _raw_message(body: dict, receipt_handle: str = "rh-1") -> dict:
    return {
        "Body": json.dumps(body),
        "ReceiptHandle": receipt_handle,
        "MessageId": "msg-1",
    }


def _sns_envelope(inner: dict, receipt_handle: str = "rh-sns") -> dict:
    envelope = {
        "Type": "Notification",
        "Message": json.dumps(inner),
    }
    return {
        "Body": json.dumps(envelope),
        "ReceiptHandle": receipt_handle,
        "MessageId": "msg-sns",
    }


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_empty_queue_url_raises_value_error():
    with pytest.raises(ValueError, match="SQS queue URL must be provided"):
        AwsSqsConsumer(queue_url="")


# ---------------------------------------------------------------------------
# poll_raw_message — empty queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_raw_message_yields_none_when_queue_is_empty():
    consumer = AwsSqsConsumer(queue_url=QUEUE_URL)
    client = _make_sqs_client(messages=[])

    # Patch session.client to return our mock
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    consumer.session.client = MagicMock(return_value=mock_ctx)

    async with consumer.poll_raw_message() as msg:
        assert msg is None

    client.get_queue_url.assert_not_awaited()


# ---------------------------------------------------------------------------
# poll_raw_message — standard JSON message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_raw_message_yields_ackable_message_for_plain_json():
    consumer = AwsSqsConsumer(queue_url=QUEUE_URL)
    payload = {"event_type": "order.created", "id": "evt-1"}
    client = _make_sqs_client(messages=[_raw_message(payload)])

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    consumer.session.client = MagicMock(return_value=mock_ctx)

    async with consumer.poll_raw_message() as msg:
        assert isinstance(msg, AckableMessage)
        assert msg.payload == payload


# ---------------------------------------------------------------------------
# poll_raw_message — SNS envelope unwrapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_raw_message_unwraps_sns_notification_envelope():
    consumer = AwsSqsConsumer(queue_url=QUEUE_URL)
    inner_payload = {"event_type": "invoice.created", "tenant_id": "t1"}
    client = _make_sqs_client(messages=[_sns_envelope(inner_payload)])

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    consumer.session.client = MagicMock(return_value=mock_ctx)

    async with consumer.poll_raw_message() as msg:
        assert isinstance(msg, AckableMessage)
        assert msg.payload == inner_payload


# ---------------------------------------------------------------------------
# ack and nack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ack_deletes_message_from_sqs():
    consumer = AwsSqsConsumer(queue_url=QUEUE_URL)
    payload = {"event_type": "test.event"}
    client = _make_sqs_client(messages=[_raw_message(payload, receipt_handle="rh-abc")])

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    consumer.session.client = MagicMock(return_value=mock_ctx)

    async with consumer.poll_raw_message() as msg:
        await msg.ack()

    client.delete_message.assert_awaited_once_with(QueueUrl=QUEUE_URL, ReceiptHandle="rh-abc")


@pytest.mark.asyncio
async def test_nack_is_a_no_op():
    """nack() does nothing — SQS will redeliver the message after visibility timeout."""
    consumer = AwsSqsConsumer(queue_url=QUEUE_URL)
    payload = {"event_type": "test.event"}
    client = _make_sqs_client(messages=[_raw_message(payload)])

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    consumer.session.client = MagicMock(return_value=mock_ctx)

    async with consumer.poll_raw_message() as msg:
        await msg.nack()  # should not raise

    # nack does NOT call delete — message stays in SQS
    client.delete_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# JSON decode failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_json_decode_error_deletes_message_and_yields_none():
    """Malformed JSON is treated as a dead letter: delete it and yield None."""
    consumer = AwsSqsConsumer(queue_url=QUEUE_URL)
    invalid_msg = {
        "Body": "NOT_VALID_JSON{{{{",
        "ReceiptHandle": "rh-bad",
        "MessageId": "msg-bad",
    }
    client = _make_sqs_client(messages=[invalid_msg])

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    consumer.session.client = MagicMock(return_value=mock_ctx)

    async with consumer.poll_raw_message() as msg:
        assert msg is None

    # The malformed message must be deleted to prevent infinite loop
    client.delete_message.assert_awaited_once_with(QueueUrl=QUEUE_URL, ReceiptHandle="rh-bad")


# ---------------------------------------------------------------------------
# Context manager lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_manager_creates_and_destroys_shared_client():
    consumer = AwsSqsConsumer(queue_url=QUEUE_URL)

    mock_client = AsyncMock()
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)
    consumer.session.client = MagicMock(return_value=mock_client_ctx)

    assert consumer._client is None

    async with consumer:
        assert consumer._client is mock_client

    assert consumer._client is None  # cleaned up on exit


@pytest.mark.asyncio
async def test_context_manager_reuses_existing_client_on_double_enter():
    """Calling __aenter__ twice should not create a second client."""
    consumer = AwsSqsConsumer(queue_url=QUEUE_URL)

    mock_client = AsyncMock()
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)
    consumer.session.client = MagicMock(return_value=mock_client_ctx)

    async with consumer, consumer:  # second enter should be a no-op
        pass

    # session.client should only have been called once
    consumer.session.client.assert_called_once()


# ---------------------------------------------------------------------------
# poll_raw_message — uses shared client when available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_raw_message_uses_shared_client_when_available():
    """When used inside a context manager, poll_raw_message should reuse the shared client."""
    consumer = AwsSqsConsumer(queue_url=QUEUE_URL)
    payload = {"event_type": "shared.client.event"}
    shared_client = _make_sqs_client(messages=[_raw_message(payload)])

    # Inject shared client directly (simulating inside `async with consumer:`)
    consumer._client = shared_client

    async with consumer.poll_raw_message() as msg:
        assert isinstance(msg, AckableMessage)
        assert msg.payload == payload

    # The shared client's receive_message was used, not a newly-created one
    shared_client.receive_message.assert_awaited_once()


# ---------------------------------------------------------------------------
# Exception Handling in poll_raw_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_raw_message_catches_and_logs_exception_from_caller():
    """
    If the caller raises an exception inside the async with block, it is caught
    by the context manager, logged, and suppresses the error to prevent loop crash.
    """
    consumer = AwsSqsConsumer(QUEUE_URL)
    mock_client = AsyncMock()
    mock_client.receive_message.return_value = {
        "Messages": [
            {
                "ReceiptHandle": "receipt",
                "MessageId": "msg1",
                "Body": '{"event_type": "test"}',
            }
        ]
    }

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_client

    with patch.object(consumer.session, "client", return_value=mock_cm):
        async with consumer.poll_raw_message():
            raise RuntimeError("caller failure")

    # The context manager swallows the error (as intended on lines 150-167).
    # Since it yielded, it does not yield None again.


@pytest.mark.asyncio
async def test_poll_raw_message_reraises_client_error():
    """ClientError during receive_message is logged and re-raised."""
    from botocore.exceptions import ClientError

    consumer = AwsSqsConsumer(QUEUE_URL)
    mock_client = AsyncMock()
    mock_client.receive_message.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Denied"}},
        "ReceiveMessage",
    )

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_client

    with patch.object(consumer.session, "client", return_value=mock_cm), pytest.raises(ClientError):
        async with consumer.poll_raw_message():
            pass
