"""Unit tests for Stitch CRUD use cases (Get, Update, ToggleState, Delete)."""

from __future__ import annotations

from types import TracebackType

import pytest
from ip.engine.adapters.outbound.stitches.stitch_catalog_registry import (
    InMemoryStitchCatalogRegistry,
)
from ip.engine.application.use_cases.stitch.delete_stitch_use_case import (
    DeleteStitchCommand,
    DeleteStitchUseCase,
)
from ip.engine.application.use_cases.stitch.get_stitch_use_case import (
    GetStitchQuery,
    GetStitchUseCase,
)
from ip.engine.application.use_cases.stitch.toggle_stitch_state_use_case import (
    ToggleStitchStateCommand,
    ToggleStitchStateUseCase,
)
from ip.engine.application.use_cases.stitch.update_stitch_use_case import (
    UpdateStitchCommand,
    UpdateStitchUseCase,
)
from ip.engine.domain.exceptions import IpErrorCode
from ip.engine.domain.stitch.stitch import Stitch
from ip.engine.ports.outbound.connection_entity_repository_port import (
    ConnectionEntityRepositoryPort,
)
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.mapping_spec_repository_port import (
    MappingSpecRepositoryPort,
)
from ip.engine.ports.outbound.stitch_repository_port import StitchRepositoryPort
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.transformation_repository_port import (
    TransformationRepositoryPort,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort
from ip.engine.ports.outbound.webhook_endpoint_repository_port import (
    WebhookEndpointRepositoryPort,
)


class _StubStitchRepo(StitchRepositoryPort):
    def __init__(self) -> None:
        self.items: dict[str, Stitch] = {}

    async def save(self, stitch: Stitch) -> None:
        self.items[stitch.id] = stitch

    async def get_by_id(self, *, tenant_id: str, stitch_id: str) -> Stitch | None:
        s = self.items.get(stitch_id)
        if s and (s.tenant_id == tenant_id or s.tenant_id == "*"):
            return s
        return None

    async def get_by_id_global(self, *, stitch_id: str) -> Stitch | None:
        return self.items.get(stitch_id)

    async def list_by_tenant(self, *, tenant_id: str) -> list[Stitch]:
        return [s for s in self.items.values() if s.tenant_id in (tenant_id, "*")]

    async def list_for_event(self, *, tenant_id: str, canonical_event_type: str) -> list[Stitch]:
        return [
            s
            for s in self.items.values()
            if s.canonical_event_type == canonical_event_type and s.is_active
        ]

    async def list_by_mapping_spec_id(
        self, *, tenant_id: str, mapping_spec_id: str
    ) -> list[Stitch]:
        return [
            s
            for s in self.items.values()
            if s.tenant_id in (tenant_id, "*") and s.mapping_spec_id == mapping_spec_id
        ]

    async def delete(self, *, tenant_id: str, stitch_id: str) -> None:
        if stitch_id in self.items:
            del self.items[stitch_id]


class _StubControlPlaneUoW(IpControlPlaneUnitOfWorkPort):
    def __init__(self) -> None:
        self.stitches = _StubStitchRepo()
        self.committed = False

    @property
    def connections(self) -> ConnectionRepositoryPort:
        raise NotImplementedError

    @property
    def mapping_specs(self) -> MappingSpecRepositoryPort:
        raise NotImplementedError

    @property
    def entities(self) -> ConnectionEntityRepositoryPort:
        raise NotImplementedError

    @property
    def sync_runs(self) -> SyncRunRepositoryPort:
        raise NotImplementedError

    @property
    def transformations(self) -> TransformationRepositoryPort:
        raise NotImplementedError

    @property
    def webhook_endpoints(self) -> WebhookEndpointRepositoryPort:
        raise NotImplementedError

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass

    async def __aenter__(self) -> _StubControlPlaneUoW:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass


def _create_sample_stitch(
    stitch_id: str = "stch_1",
    tenant_id: str = "tenant_test",
    is_active: bool = True,
) -> Stitch:
    return Stitch(
        id=stitch_id,
        tenant_id=tenant_id,
        name="Telemetry Pipeline",
        description="Routes telemetry",
        target_workflow_id="wf_telemetry",
        canonical_event_type="canonical.telemetry",
        mapping_spec_id="fmap_spec_1",
        is_active=is_active,
    )


@pytest.mark.asyncio
async def test_get_stitch_resolves_definition() -> None:
    catalog = InMemoryStitchCatalogRegistry()
    uow = _StubControlPlaneUoW()
    stitch = _create_sample_stitch("stch_uow")
    await uow.stitches.save(stitch)

    use_case = GetStitchUseCase(stitch_catalog=catalog, uow=uow)
    res = await use_case.execute(GetStitchQuery(tenant_id="tenant_test", stitch_id="stch_uow"))
    assert res.is_ok
    dto = res.unwrap()
    assert dto.id == "stch_uow"
    assert dto.name == "Telemetry Pipeline"

    # From catalog fallback
    stitch_cat = _create_sample_stitch("stch_cat")
    catalog.register_stitch(stitch_cat)
    res_cat = await use_case.execute(GetStitchQuery(tenant_id="tenant_test", stitch_id="stch_cat"))
    assert res_cat.is_ok
    assert res_cat.unwrap().id == "stch_cat"

    # Not found
    res_missing = await use_case.execute(
        GetStitchQuery(tenant_id="tenant_test", stitch_id="stch_missing")
    )
    assert res_missing.is_err
    assert res_missing.unwrap_err().code == IpErrorCode.STITCH_NOT_FOUND


@pytest.mark.asyncio
async def test_update_stitch_modifies_configuration() -> None:
    catalog = InMemoryStitchCatalogRegistry()
    uow = _StubControlPlaneUoW()
    stitch = _create_sample_stitch("stch_upd")
    await uow.stitches.save(stitch)

    use_case = UpdateStitchUseCase(stitch_catalog=catalog, uow=uow)
    res = await use_case.execute(
        UpdateStitchCommand(
            tenant_id="tenant_test",
            stitch_id="stch_upd",
            name="Updated Pipeline Name",
            description="New description",
            mapping_spec_id="fmap_new_spec",
            is_active=False,
        )
    )
    assert res.is_ok
    dto = res.unwrap()
    assert dto.name == "Updated Pipeline Name"
    assert dto.description == "New description"
    assert dto.mapping_spec_id == "fmap_new_spec"
    assert dto.is_active is False
    assert uow.committed

    # Verify synced to in-memory catalog
    synced = catalog.get_stitch(tenant_id="tenant_test", stitch_id="stch_upd")
    assert synced is not None
    assert synced.name == "Updated Pipeline Name"
    assert synced.is_active is False


@pytest.mark.asyncio
async def test_toggle_stitch_state() -> None:
    catalog = InMemoryStitchCatalogRegistry()
    uow = _StubControlPlaneUoW()
    stitch = _create_sample_stitch("stch_toggle", is_active=True)
    await uow.stitches.save(stitch)

    use_case = ToggleStitchStateUseCase(stitch_catalog=catalog, uow=uow)
    res_pause = await use_case.execute(
        ToggleStitchStateCommand(tenant_id="tenant_test", stitch_id="stch_toggle", is_active=False)
    )
    assert res_pause.is_ok
    assert res_pause.unwrap().is_active is False

    res_activate = await use_case.execute(
        ToggleStitchStateCommand(tenant_id="tenant_test", stitch_id="stch_toggle", is_active=True)
    )
    assert res_activate.is_ok
    assert res_activate.unwrap().is_active is True


@pytest.mark.asyncio
async def test_delete_stitch_removes_from_all_stores() -> None:
    catalog = InMemoryStitchCatalogRegistry()
    uow = _StubControlPlaneUoW()
    stitch = _create_sample_stitch("stch_del")
    await uow.stitches.save(stitch)
    catalog.register_stitch(stitch)

    use_case = DeleteStitchUseCase(stitch_catalog=catalog, uow=uow)
    res = await use_case.execute(DeleteStitchCommand(tenant_id="tenant_test", stitch_id="stch_del"))
    assert res.is_ok
    assert await uow.stitches.get_by_id(tenant_id="tenant_test", stitch_id="stch_del") is None
    assert catalog.get_stitch(tenant_id="tenant_test", stitch_id="stch_del") is None
    assert uow.committed

    # Deleting missing returns 404
    res_missing = await use_case.execute(
        DeleteStitchCommand(tenant_id="tenant_test", stitch_id="stch_del")
    )
    assert res_missing.is_err
    assert res_missing.unwrap_err().code == IpErrorCode.STITCH_NOT_FOUND
