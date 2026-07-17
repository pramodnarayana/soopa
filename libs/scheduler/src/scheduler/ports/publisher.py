import typing


class MessagePublisherPort(typing.Protocol):
    async def publish(self, queue_name: str, payload: dict[str, typing.Any]) -> None: ...
