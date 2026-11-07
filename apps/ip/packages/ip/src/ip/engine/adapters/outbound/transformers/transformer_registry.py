"""Generic registry of pure domain TransformerHookPort implementations."""

from __future__ import annotations

from ip.engine.ports.outbound.transformer_hook_port import TransformerHookPort


class TransformerRegistry:
    """In-memory registry mapping app_id (and optional stream_name) to TransformerHookPort."""

    def __init__(self) -> None:
        self._by_app_and_stream: dict[tuple[str, str], TransformerHookPort] = {}
        self._by_app: dict[str, TransformerHookPort] = {}

    def register(
        self,
        app_id: str,
        transformer: TransformerHookPort,
        stream_name: str | None = None,
    ) -> None:
        """Registers a pure TransformerHookPort for an app_id (and optional specific stream)."""
        if stream_name:
            self._by_app_and_stream[(app_id, stream_name)] = transformer
        else:
            self._by_app[app_id] = transformer

    def resolve(self, app_id: str, stream_name: str | None = None) -> TransformerHookPort | None:
        """Resolves a registered TransformerHookPort for the given app_id and optional stream."""
        if stream_name:
            specific = self._by_app_and_stream.get((app_id, stream_name))
            if specific is not None:
                return specific
        return self._by_app.get(app_id)
