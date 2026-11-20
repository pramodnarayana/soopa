"""In-memory thread-safe registry for solution connectors, transformers, mutations, and stitches."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from orchestration.domain.definition import RetryPolicy

from ip.sdk.specs import ConnectorSpec, MutationSpec, StitchSpec, TransformerSpec


class DomainFunctionKind(StrEnum):
    """Categorization of solution domain functions."""

    CONNECTOR = "CONNECTOR"
    TRANSFORMER = "TRANSFORMER"
    MUTATION = "MUTATION"
    STITCH = "STITCH"


@dataclass(frozen=True, kw_only=True)
class DomainFunctionDescriptor:
    """Metadata describing a registered solution domain function."""

    kind: DomainFunctionKind
    app: str = ""
    entity: str = ""
    operation: str = ""
    stitch_id: str = ""
    on_event: str = ""
    concurrency_key: str | None = None
    retry_policy: RetryPolicy | None = None
    step_timeout: timedelta | None = None
    workflow_sla: timedelta | None = None
    name: str = ""
    description: str = ""
    fn: Callable[..., object]


class DomainFunctionRegistry:
    """Thread-safe registry for discovering and executing solution functions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connectors: dict[tuple[str, str], DomainFunctionDescriptor] = {}
        self._transformers: dict[tuple[str, str], DomainFunctionDescriptor] = {}
        self._mutations: dict[tuple[str, str, str], DomainFunctionDescriptor] = {}
        self._stitches: dict[str, DomainFunctionDescriptor] = {}

    def register_connector(
        self,
        app_or_spec: str | ConnectorSpec | None = None,
        entity: str | None = None,
        fn: Callable[..., object] | None = None,
        *,
        app: str | None = None,
    ) -> DomainFunctionDescriptor:
        resolved_app = app_or_spec if app_or_spec is not None else app
        if resolved_app is None:
            raise ValueError("register_connector requires app_or_spec or app keyword argument")
        if isinstance(resolved_app, ConnectorSpec):
            target_app = resolved_app.app
            ent = resolved_app.entity
            target_fn = resolved_app.fn
            desc_text = resolved_app.description
        else:
            if entity is None or fn is None:
                raise ValueError("register_connector requires entity and fn when app is a string")
            target_app = resolved_app
            ent = entity
            target_fn = fn
            desc_text = ""

        desc = DomainFunctionDescriptor(
            kind=DomainFunctionKind.CONNECTOR,
            app=target_app.strip().lower(),
            entity=ent.strip().lower(),
            description=desc_text,
            fn=target_fn,
        )
        with self._lock:
            self._connectors[(desc.app, desc.entity)] = desc
        return desc

    def register_transformer(
        self,
        app_or_spec: str | TransformerSpec | None = None,
        entity: str | None = None,
        fn: Callable[..., object] | None = None,
        *,
        app: str | None = None,
    ) -> DomainFunctionDescriptor:
        resolved_app = app_or_spec if app_or_spec is not None else app
        if resolved_app is None:
            raise ValueError("register_transformer requires app_or_spec or app keyword argument")
        if isinstance(resolved_app, TransformerSpec):
            target_app = resolved_app.app
            ent = resolved_app.entity
            target_fn = resolved_app.fn
            desc_text = resolved_app.description
        else:
            if entity is None or fn is None:
                raise ValueError("register_transformer requires entity and fn when app is a string")
            target_app = resolved_app
            ent = entity
            target_fn = fn
            desc_text = ""

        desc = DomainFunctionDescriptor(
            kind=DomainFunctionKind.TRANSFORMER,
            app=target_app.strip().lower(),
            entity=ent.strip().lower(),
            description=desc_text,
            fn=target_fn,
        )
        with self._lock:
            self._transformers[(desc.app, desc.entity)] = desc
        return desc

    def register_mutation(
        self,
        app_or_spec: str | MutationSpec | None = None,
        entity: str | None = None,
        operation: str | None = None,
        fn: Callable[..., object] | None = None,
        *,
        app: str | None = None,
    ) -> DomainFunctionDescriptor:
        resolved_app = app_or_spec if app_or_spec is not None else app
        if resolved_app is None:
            raise ValueError("register_mutation requires app_or_spec or app keyword argument")
        if isinstance(resolved_app, MutationSpec):
            target_app = resolved_app.app
            ent = resolved_app.entity
            op = resolved_app.operation
            target_fn = resolved_app.fn
            desc_text = resolved_app.description
        else:
            if entity is None or operation is None or fn is None:
                raise ValueError(
                    "register_mutation requires entity, operation, and fn when app is a string"
                )
            target_app = resolved_app
            ent = entity
            op = operation
            target_fn = fn
            desc_text = ""

        desc = DomainFunctionDescriptor(
            kind=DomainFunctionKind.MUTATION,
            app=target_app.strip().lower(),
            entity=ent.strip().lower(),
            operation=op.strip().upper(),
            description=desc_text,
            fn=target_fn,
        )
        with self._lock:
            self._mutations[(desc.app, desc.entity, desc.operation)] = desc
        return desc

    def register_stitch(
        self,
        spec: StitchSpec | None = None,
        *,
        stitch_id: str | None = None,
        on: str | None = None,
        fn: Callable[..., object] | None = None,
        concurrency_key: str | None = None,
        retry: RetryPolicy | None = None,
        step_timeout: timedelta | None = None,
        workflow_sla: timedelta | None = None,
        name: str = "",
        description: str = "",
    ) -> DomainFunctionDescriptor:
        if spec is not None:
            sid = spec.id
            trigger = spec.trigger
            target_fn = spec.handler
            ckey = spec.concurrency_key
            rpol = spec.retry
            stimeout = spec.step_timeout
            wsla = spec.workflow_sla
            sname = spec.name or spec.id
            sdesc = spec.description
        else:
            if stitch_id is None or on is None or fn is None:
                raise ValueError(
                    "register_stitch requires stitch_id, on, and fn when spec is omitted"
                )
            sid = stitch_id
            trigger = on
            target_fn = fn
            ckey = concurrency_key
            rpol = retry
            stimeout = step_timeout
            wsla = workflow_sla
            sname = name.strip() or stitch_id
            sdesc = description.strip()

        desc = DomainFunctionDescriptor(
            kind=DomainFunctionKind.STITCH,
            stitch_id=sid.strip(),
            on_event=trigger.strip(),
            concurrency_key=ckey,
            retry_policy=rpol,
            step_timeout=stimeout,
            workflow_sla=wsla,
            name=sname,
            description=sdesc,
            fn=target_fn,
        )
        with self._lock:
            self._stitches[desc.stitch_id] = desc
        return desc

    def get_connector(self, app: str, entity: str) -> DomainFunctionDescriptor | None:
        key = (app.strip().lower(), entity.strip().lower())
        with self._lock:
            return self._connectors.get(key)

    def get_transformer(self, app: str, entity: str) -> DomainFunctionDescriptor | None:
        key = (app.strip().lower(), entity.strip().lower())
        with self._lock:
            return self._transformers.get(key)

    def get_mutation(
        self, app: str, entity: str, operation: str
    ) -> DomainFunctionDescriptor | None:
        key = (app.strip().lower(), entity.strip().lower(), operation.strip().upper())
        with self._lock:
            return self._mutations.get(key)

    def get_stitch(self, stitch_id: str) -> DomainFunctionDescriptor | None:
        with self._lock:
            return self._stitches.get(stitch_id.strip())

    def list_stitches_for_event(self, on_event: str) -> list[DomainFunctionDescriptor]:
        norm_event = on_event.strip()
        with self._lock:
            return [
                desc
                for desc in self._stitches.values()
                if desc.on_event == norm_event or desc.on_event == "*"
            ]

    def list_stitches(self) -> list[DomainFunctionDescriptor]:
        with self._lock:
            return list(self._stitches.values())

    def clear(self) -> None:
        with self._lock:
            self._connectors.clear()
            self._transformers.clear()
            self._mutations.clear()
            self._stitches.clear()


default_registry = DomainFunctionRegistry()

__all__ = [
    "DomainFunctionDescriptor",
    "DomainFunctionKind",
    "DomainFunctionRegistry",
    "default_registry",
]
