from typing import Any, Protocol


class SQSClientProtocol(Protocol):
    async def get_queue_url(self, QueueName: str) -> dict[str, Any]: ...

    async def receive_message(
        self, QueueUrl: str, MaxNumberOfMessages: int, WaitTimeSeconds: int
    ) -> dict[str, Any]: ...

    async def delete_message(self, QueueUrl: str, ReceiptHandle: str) -> dict[str, Any]: ...

    async def send_message(
        self,
        QueueUrl: str,
        MessageBody: str,
        MessageGroupId: str,
        MessageDeduplicationId: str,
    ) -> dict[str, Any]: ...

    async def send_message_batch(
        self, QueueUrl: str, Entries: list[dict[str, Any]]
    ) -> dict[str, Any]: ...


class SQSClientContextProtocol(Protocol):
    async def __aenter__(self) -> SQSClientProtocol: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None: ...
