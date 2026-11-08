import json

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.exceptions import ConsumerTerminalError, ConsumerTransientError
from seedwork.domain.types import JsonDict


def _make_client_error(code: str, message: str = "error") -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": message}},
        operation_name="MockOperation",
    )


class FakeSqsClient:
    def __init__(
        self,
        messages: list[JsonDict] | None = None,
        receive_error: Exception | None = None,
        delete_error: Exception | None = None,
        visibility_error: Exception | None = None,
    ) -> None:
        self.messages: list[JsonDict] = list(messages or [])
        self.deleted_messages: list[tuple[str, str]] = []
        self.visibility_changes: list[tuple[str, str, int]] = []
        self.receive_error = receive_error
        self.delete_error = delete_error
        self.visibility_error = visibility_error

    async def receive_message(self, **kwargs: object) -> JsonDict:
        if self.receive_error:
            raise self.receive_error
        if self.messages:
            msg = self.messages.pop(0)
            return {"Messages": [msg]}
        return {"Messages": []}

    async def delete_message(self, **kwargs: object) -> None:
        if self.delete_error:
            raise self.delete_error
        queue_url = str(kwargs.get("QueueUrl", ""))
        receipt_handle = str(kwargs.get("ReceiptHandle", ""))
        self.deleted_messages.append((queue_url, receipt_handle))

    async def change_message_visibility(self, **kwargs: object) -> None:
        if self.visibility_error:
            raise self.visibility_error
        queue_url = str(kwargs.get("QueueUrl", ""))
        receipt_handle = str(kwargs.get("ReceiptHandle", ""))
        raw_timeout = kwargs.get("VisibilityTimeout", 0)
        timeout = int(raw_timeout) if isinstance(raw_timeout, (int, str)) else 0
        self.visibility_changes.append((queue_url, receipt_handle, timeout))


def test_aws_sqs_consumer_init_validation() -> None:
    with pytest.raises(ValueError, match="SQS queue URL must be provided"):
        AwsSqsConsumer(queue_url="")

    with pytest.raises(ValueError, match="wait_time_seconds must be between 0 and 20"):
        AwsSqsConsumer(queue_url="https://sqs.us-east-1.amazonaws.com/123/q", wait_time_seconds=-1)

    with pytest.raises(ValueError, match="wait_time_seconds must be between 0 and 20"):
        AwsSqsConsumer(queue_url="https://sqs.us-east-1.amazonaws.com/123/q", wait_time_seconds=21)

    consumer = AwsSqsConsumer(
        queue_url="https://sqs.us-east-1.amazonaws.com/123/q", wait_time_seconds=15
    )
    assert consumer.queue_url == "https://sqs.us-east-1.amazonaws.com/123/q"
    assert consumer.wait_time_seconds == 15


def test_extract_event_payload_direct_dict() -> None:
    payload = AwsSqsConsumer._extract_event_payload('{"key": "value"}')
    assert payload == {"key": "value"}


def test_extract_event_payload_sns_unwrapping() -> None:
    inner = json.dumps({"event": "order.created", "id": 123})
    sns_envelope = json.dumps({"Type": "Notification", "Message": inner})
    payload = AwsSqsConsumer._extract_event_payload(sns_envelope)
    assert payload == {"event": "order.created", "id": 123}


def test_extract_event_payload_sns_non_dict_message_raises() -> None:
    sns_envelope = json.dumps({"Type": "Notification", "Message": '"a raw string"'})
    with pytest.raises(ValueError, match="Unwrapped SNS payload is not a JSON object"):
        AwsSqsConsumer._extract_event_payload(sns_envelope)


def test_extract_event_payload_non_dict_raw_raises() -> None:
    with pytest.raises(TypeError, match="SQS payload is not a JSON object"):
        AwsSqsConsumer._extract_event_payload("[1, 2, 3]")


def test_handle_client_error_terminal() -> None:
    for code in (
        "AWS.SimpleQueueService.NonExistentQueue",
        "InvalidParameterValue",
        "AccessDenied",
    ):
        with pytest.raises(ConsumerTerminalError):
            AwsSqsConsumer._handle_client_error(_make_client_error(code))


def test_handle_client_error_transient() -> None:
    with pytest.raises(ConsumerTransientError):
        AwsSqsConsumer._handle_client_error(_make_client_error("ServiceUnavailable"))


@pytest.mark.asyncio
async def test_receive_single_message_empty() -> None:
    consumer = AwsSqsConsumer(queue_url="https://sqs.us-east-1.amazonaws.com/123/q")
    fake_client = FakeSqsClient()
    result = await consumer._receive_single_message(fake_client)
    assert result is None


@pytest.mark.asyncio
async def test_receive_single_message_client_error() -> None:
    consumer = AwsSqsConsumer(queue_url="https://sqs.us-east-1.amazonaws.com/123/q")
    fake_client = FakeSqsClient(receive_error=_make_client_error("AccessDenied"))
    with pytest.raises(ConsumerTerminalError):
        await consumer._receive_single_message(fake_client)


@pytest.mark.asyncio
async def test_receive_single_message_botocore_error() -> None:
    consumer = AwsSqsConsumer(queue_url="https://sqs.us-east-1.amazonaws.com/123/q")
    fake_client = FakeSqsClient(receive_error=BotoCoreError())
    with pytest.raises(ConsumerTransientError):
        await consumer._receive_single_message(fake_client)


@pytest.mark.asyncio
async def test_delete_message_success_and_errors() -> None:
    consumer = AwsSqsConsumer(queue_url="https://sqs.us-east-1.amazonaws.com/123/q")
    fake_client = FakeSqsClient()
    await consumer._delete_message(fake_client, "handle-1")
    assert fake_client.deleted_messages == [
        ("https://sqs.us-east-1.amazonaws.com/123/q", "handle-1")
    ]

    failing_client_term = FakeSqsClient(delete_error=_make_client_error("AccessDenied"))
    with pytest.raises(ConsumerTerminalError):
        await consumer._delete_message(failing_client_term, "handle-2")

    failing_client_boto = FakeSqsClient(delete_error=BotoCoreError())
    with pytest.raises(ConsumerTransientError):
        await consumer._delete_message(failing_client_boto, "handle-3")


@pytest.mark.asyncio
async def test_poll_raw_message_ack_and_nack_lifecycle() -> None:
    consumer = AwsSqsConsumer(queue_url="https://sqs.us-east-1.amazonaws.com/123/q")
    fake_client = FakeSqsClient(
        messages=[
            {
                "MessageId": "msg-1",
                "ReceiptHandle": "rcpt-1",
                "Body": json.dumps({"action": "ship"}),
            },
            {
                "MessageId": "msg-2",
                "ReceiptHandle": "rcpt-2",
                "Body": json.dumps({"action": "retry"}),
            },
        ]
    )
    consumer._client = fake_client

    # First message -> ACK
    async with consumer.poll_raw_message() as ackable:
        assert ackable is not None
        assert ackable.payload == {"action": "ship"}
        await ackable.ack()

    assert fake_client.deleted_messages == [("https://sqs.us-east-1.amazonaws.com/123/q", "rcpt-1")]

    # Second message -> NACK
    async with consumer.poll_raw_message() as ackable:
        assert ackable is not None
        assert ackable.payload == {"action": "retry"}
        await ackable.nack()

    assert fake_client.visibility_changes == [
        ("https://sqs.us-east-1.amazonaws.com/123/q", "rcpt-2", 5)
    ]


@pytest.mark.asyncio
async def test_poll_raw_message_malformed_json_deletes_and_yields_none() -> None:
    consumer = AwsSqsConsumer(queue_url="https://sqs.us-east-1.amazonaws.com/123/q")
    fake_client = FakeSqsClient(
        messages=[
            {
                "MessageId": "bad-msg-1",
                "ReceiptHandle": "bad-rcpt-1",
                "Body": "not a valid {json string",
            }
        ]
    )
    consumer._client = fake_client

    async with consumer.poll_raw_message() as ackable:
        assert ackable is None

    # Bad message must be deleted to prevent infinite poison pill loops
    assert fake_client.deleted_messages == [
        ("https://sqs.us-east-1.amazonaws.com/123/q", "bad-rcpt-1")
    ]


@pytest.mark.asyncio
async def test_nack_handles_client_error_without_raising() -> None:
    consumer = AwsSqsConsumer(queue_url="https://sqs.us-east-1.amazonaws.com/123/q")
    fake_client = FakeSqsClient(
        messages=[
            {
                "MessageId": "msg-nack-err",
                "ReceiptHandle": "rcpt-nack-err",
                "Body": json.dumps({"retry": True}),
            }
        ],
        visibility_error=_make_client_error("ServiceUnavailable"),
    )
    consumer._client = fake_client

    async with consumer.poll_raw_message() as ackable:
        assert ackable is not None
        # Should not raise exception
        await ackable.nack()


@pytest.mark.asyncio
async def test_poll_raw_message_nack_applies_custom_visibility_timeout() -> None:
    consumer = AwsSqsConsumer(queue_url="https://sqs.us-east-1.amazonaws.com/123/q")
    fake_client = FakeSqsClient(
        messages=[
            {
                "MessageId": "msg-vis-1",
                "ReceiptHandle": "rcpt-vis-1",
                "Body": json.dumps({"action": "rate_limit"}),
            },
            {
                "MessageId": "msg-vis-2",
                "ReceiptHandle": "rcpt-vis-2",
                "Body": json.dumps({"action": "clamp_max"}),
            },
        ]
    )
    consumer._client = fake_client

    async with consumer.poll_raw_message() as ackable:
        assert ackable is not None
        await ackable.nack(visibility_timeout_seconds=42)

    async with consumer.poll_raw_message() as ackable:
        assert ackable is not None
        await ackable.nack(visibility_timeout_seconds=99999)

    assert fake_client.visibility_changes == [
        ("https://sqs.us-east-1.amazonaws.com/123/q", "rcpt-vis-1", 42),
        ("https://sqs.us-east-1.amazonaws.com/123/q", "rcpt-vis-2", 43200),
    ]


@pytest.mark.asyncio
async def test_context_manager_reuse() -> None:
    consumer = AwsSqsConsumer(queue_url="https://sqs.us-east-1.amazonaws.com/123/q")

    class FakeClientContext:
        def __init__(self) -> None:
            self.entered = False
            self.exited = False

        async def __aenter__(self) -> FakeSqsClient:
            self.entered = True
            return FakeSqsClient()

        async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
            self.exited = True

    fake_ctx = FakeClientContext()

    class FakeSession:
        def client(self, *args: object, **kwargs: object) -> FakeClientContext:
            return fake_ctx

    consumer.session = FakeSession()

    async with consumer as entered_consumer:
        assert entered_consumer is consumer
        assert fake_ctx.entered is True
        assert consumer._client is not None

    assert fake_ctx.exited is True
    assert consumer._client is None
