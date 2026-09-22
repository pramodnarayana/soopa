from typing import Protocol, runtime_checkable


@runtime_checkable
class LaunchableWorker(Protocol):
    """
    Enterprise Standard:
    Every background worker module must implement this exact protocol.
    The unified runner will blindly call `await start()` and `await stop()`.
    """

    async def start(self) -> None:
        """Start the background worker tasks."""
        ...

    async def stop(self) -> None:
        """Gracefully stop the background worker tasks."""
        ...
