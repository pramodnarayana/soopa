"""AWS SQS and SNS message publisher adapter implementing MessagePublisherPort."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import aioboto3
import structlog
from seedwork.domain.exceptions import Result
from seedwork.events import EventEnvelope

from pubsub.domain.dtos import PublishResultDTO
from pubsub.domain.exceptions import PublisherError
from pubsub.ports.message_publisher_port import MessagePublisherPort

logger = structlog.get_logger(__name__)


class AwsMessagePublisherAdapter(MessagePublisherPort):
    """Universal publisher for AWS SQS and SNS destinations."""

    def __init__(
        self,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
    ) -> None:
        self._region_name = region_name
        self._endpoint_url = endpoint_url
        self._session = aioboto3.Session()

    def _client_kwargs(self) -> dict[str, str]:
        kwargs: dict[str, str] = {"region_name": self._region_name}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        return kwargs

    async def publish(
        self,
        destination_uri: str,
        message: bytes | EventEnvelope,
        key: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Result[PublishResultDTO, Exception]:
        is_sns = (
            destination_uri.startswith(("sns://", "arn:aws:sns"))
            or "arn:aws:sns" in destination_uri.lower()
        )
        is_sqs = (
            destination_uri.startswith(("sqs://", "arn:aws:sqs"))
            or "queue" in destination_uri.lower()
        )

        if isinstance(message, EventEnvelope):
            raw_body = json.dumps(message.to_dict())
            event_id = message.id
        else:
            raw_body = (
                message.decode("utf-8", errors="replace")
                if isinstance(message, bytes)
                else str(message)
            )
            event_id = "msg"

        target = destination_uri.removeprefix("sqs://").removeprefix("sns://")

        try:
            if is_sns:
                async with self._session.client("sns", **self._client_kwargs()) as client:
                    resp = await client.publish(
                        TopicArn=target,
                        Message=raw_body,
                    )
                    return Result.ok(
                        PublishResultDTO(
                            destination_uri=destination_uri,
                            message_id=str(resp.get("MessageId", event_id)),
                        )
                    )
            elif is_sqs:
                async with self._session.client("sqs", **self._client_kwargs()) as client:
                    resp = await client.send_message(
                        QueueUrl=target,
                        MessageBody=raw_body,
                    )
                    return Result.ok(
                        PublishResultDTO(
                            destination_uri=destination_uri,
                            message_id=str(resp.get("MessageId", event_id)),
                        )
                    )
            else:
                return Result.fail(
                    PublisherError(f"Unsupported AWS destination URI: {destination_uri}")
                )
        except Exception as exc:  # noqa: BLE001 - Result pattern boundary captures transport exceptions into Result.fail
            logger.error("aws_publish_failed", destination=destination_uri, error=str(exc))
            return Result.fail(PublisherError(f"AWS publish failed for {destination_uri}: {exc}"))

    async def publish_batch(
        self,
        destination_uri: str,
        messages: Sequence[bytes | EventEnvelope],
        keys: Sequence[bytes | None] | None = None,
        headers: Sequence[Mapping[str, str] | None] | None = None,
    ) -> Result[tuple[PublishResultDTO, ...], Exception]:
        results: list[PublishResultDTO] = []
        for idx, msg in enumerate(messages):
            k = keys[idx] if keys and idx < len(keys) else None
            h = headers[idx] if headers and idx < len(headers) else None
            res = await self.publish(destination_uri, msg, key=k, headers=h)
            if res.is_err:
                err = res.error if res.error is not None else Exception("Unknown error")
                return Result.fail(err)
            results.append(res.unwrap())
        return Result.ok(tuple(results))
