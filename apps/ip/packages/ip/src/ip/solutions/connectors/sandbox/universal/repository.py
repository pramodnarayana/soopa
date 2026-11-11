"""SQLAlchemy repository and session-scoped reader adapters for Virtual Sandboxes (`ip.simulator_sandboxes` & `ip.simulator_entities`)."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable, Sequence

import structlog
from database.provider import DatabaseProvider
from database.router import DatabaseRouterPort
from database.uow import BaseSqlAlchemyUnitOfWork
from ip.engine.domain.exceptions import (
    InvalidConnectionConfigError,
    InvalidCredentialsError,
    IpError,
    Result,
)
from ip.solutions.connectors.sandbox.universal.dto import (
    SimulatorEntityDTO,
    SimulatorSandboxDTO,
    verify_sandbox_api_key,
)
from ip.solutions.connectors.sandbox.universal.models import (
    SimulatorEntityRecord,
    SimulatorSandboxRecord,
)
from ip.solutions.connectors.sandbox.universal.ports import (
    DuplicateSimulatorEntityError,
    DuplicateSimulatorSandboxError,
    SimulatorApiProviderPort,
    SimulatorRepositoryPort,
    SimulatorSandboxReaderPort,
    SimulatorUnitOfWorkPort,
)
from ip.solutions.connectors.sandbox.universal.spec import StreamVelocityMode
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


def _sandbox_record_to_dto(record: SimulatorSandboxRecord) -> SimulatorSandboxDTO:
    """Strict explicit Data Mapper from `SimulatorSandboxRecord` to `SimulatorSandboxDTO`."""
    return SimulatorSandboxDTO(
        id=record.id,
        tenant_id=record.tenant_id,
        name=record.name,
        api_key_hash=record.api_key_hash,
        api_key_prefix=record.api_key_prefix,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _entity_record_to_dto(record: SimulatorEntityRecord) -> SimulatorEntityDTO:
    """Strict explicit Data Mapper from `SimulatorEntityRecord` to `SimulatorEntityDTO`."""
    return SimulatorEntityDTO(
        id=record.id,
        tenant_id=record.tenant_id,
        sandbox_id=record.sandbox_id,
        entity_name=record.entity_name,
        primary_key_field=record.primary_key_field,
        cursor_field=record.cursor_field,
        records_per_pull=record.records_per_pull,
        cursor_step_seconds=record.cursor_step_seconds,
        velocity_mode=StreamVelocityMode(record.velocity_mode),
        sample_blueprint=record.sample_blueprint,
        inferred_json_schema=dict(record.inferred_json_schema),
        chaos_policy=dict(record.chaos_policy),
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _update_entity_record_from_dto(record: SimulatorEntityRecord, dto: SimulatorEntityDTO) -> None:
    """Strict explicit Data Mapper mutating `SimulatorEntityRecord` fields from `SimulatorEntityDTO`."""
    record.entity_name = dto.entity_name
    record.primary_key_field = dto.primary_key_field
    record.cursor_field = dto.cursor_field
    record.records_per_pull = dto.records_per_pull
    record.cursor_step_seconds = dto.cursor_step_seconds
    record.velocity_mode = dto.velocity_mode.value
    record.sample_blueprint = dto.sample_blueprint
    record.inferred_json_schema = dict(dto.inferred_json_schema)
    record.chaos_policy = dict(dto.chaos_policy)
    record.version = dto.version
    record.updated_at = dto.updated_at


class SqlAlchemySimulatorRepository(SimulatorRepositoryPort):
    """Request-scoped SQLAlchemy repository managing `ip.simulator_sandboxes` and `ip.simulator_entities`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def authenticate_sandbox(
        self,
        *,
        sandbox_id: str,
        raw_api_key: str,
    ) -> Result[SimulatorSandboxDTO, IpError]:
        cleaned_id = sandbox_id.strip()
        if not cleaned_id:
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="sandbox_id",
                    message="Virtual sandbox 'sandbox_id' is required in public_config.",
                    details={"field": "sandbox_id"},
                )
            )
        cleaned_key = raw_api_key.strip()
        if not cleaned_key:
            return Result.fail(
                InvalidCredentialsError(
                    message="Virtual sandbox 'api_key' credential is required.",
                    details={"sandbox_id": cleaned_id},
                )
            )
        stmt = select(SimulatorSandboxRecord).where(SimulatorSandboxRecord.id == cleaned_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None or not verify_sandbox_api_key(cleaned_key, row.api_key_hash):
            return Result.fail(
                InvalidCredentialsError(
                    message="Invalid virtual sandbox ID or API key.",
                    details={"sandbox_id": cleaned_id},
                )
            )
        return Result.ok(_sandbox_record_to_dto(row))

    async def list_entities_by_sandbox(self, sandbox_id: str) -> Sequence[SimulatorEntityDTO]:
        stmt = (
            select(SimulatorEntityRecord)
            .where(SimulatorEntityRecord.sandbox_id == sandbox_id)
            .order_by(SimulatorEntityRecord.created_at.asc(), SimulatorEntityRecord.id.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_entity_record_to_dto(row) for row in rows)

    async def get_entity_by_name(
        self, sandbox_id: str, entity_name: str
    ) -> SimulatorEntityDTO | None:
        stmt = select(SimulatorEntityRecord).where(
            SimulatorEntityRecord.sandbox_id == sandbox_id,
            SimulatorEntityRecord.entity_name == entity_name,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _entity_record_to_dto(row) if row is not None else None

    async def get_sandbox_by_id(
        self, tenant_id: str, sandbox_id: str
    ) -> SimulatorSandboxDTO | None:
        stmt = select(SimulatorSandboxRecord).where(
            SimulatorSandboxRecord.tenant_id == tenant_id,
            SimulatorSandboxRecord.id == sandbox_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _sandbox_record_to_dto(row) if row is not None else None

    async def get_sandbox_by_id_for_update(
        self, tenant_id: str, sandbox_id: str
    ) -> SimulatorSandboxDTO | None:
        stmt = (
            select(SimulatorSandboxRecord)
            .where(
                SimulatorSandboxRecord.tenant_id == tenant_id,
                SimulatorSandboxRecord.id == sandbox_id,
            )
            .with_for_update()
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _sandbox_record_to_dto(row) if row is not None else None

    async def list_sandboxes_by_tenant(self, tenant_id: str) -> Sequence[SimulatorSandboxDTO]:
        stmt = (
            select(SimulatorSandboxRecord)
            .where(SimulatorSandboxRecord.tenant_id == tenant_id)
            .order_by(SimulatorSandboxRecord.created_at.asc(), SimulatorSandboxRecord.id.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_sandbox_record_to_dto(row) for row in rows)

    async def create_sandbox(
        self, sandbox: SimulatorSandboxDTO
    ) -> Result[SimulatorSandboxDTO, IpError]:
        record = SimulatorSandboxRecord(
            id=sandbox.id,
            tenant_id=sandbox.tenant_id,
            name=sandbox.name,
            api_key_hash=sandbox.api_key_hash,
            api_key_prefix=sandbox.api_key_prefix,
            created_at=sandbox.created_at,
            updated_at=sandbox.updated_at,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
        except IntegrityError:
            logger.error(
                "simulator_sandbox_duplicate_conflict",
                tenant_id=sandbox.tenant_id,
                name=sandbox.name,
            )
            return Result.fail(
                DuplicateSimulatorSandboxError.for_name(sandbox.tenant_id, sandbox.name)
            )
        return Result.ok(_sandbox_record_to_dto(record))

    async def delete_sandbox(self, tenant_id: str, sandbox_id: str) -> bool:
        stmt = (
            delete(SimulatorSandboxRecord)
            .where(
                SimulatorSandboxRecord.tenant_id == tenant_id,
                SimulatorSandboxRecord.id == sandbox_id,
            )
            .returning(SimulatorSandboxRecord.id)
        )
        deleted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        deleted = deleted_id is not None
        if deleted:
            await self._session.flush()
        return deleted

    async def get_entity_by_id(self, sandbox_id: str, entity_id: str) -> SimulatorEntityDTO | None:
        stmt = select(SimulatorEntityRecord).where(
            SimulatorEntityRecord.sandbox_id == sandbox_id,
            SimulatorEntityRecord.id == entity_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _entity_record_to_dto(row) if row is not None else None

    async def count_entities_by_sandbox(self, sandbox_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(SimulatorEntityRecord)
            .where(SimulatorEntityRecord.sandbox_id == sandbox_id)
        )
        count = (await self._session.execute(stmt)).scalar_one()
        return int(count)

    async def create_entity(
        self, entity: SimulatorEntityDTO
    ) -> Result[SimulatorEntityDTO, IpError]:
        record = SimulatorEntityRecord(
            id=entity.id,
            tenant_id=entity.tenant_id,
            sandbox_id=entity.sandbox_id,
            entity_name=entity.entity_name,
            primary_key_field=entity.primary_key_field,
            cursor_field=entity.cursor_field,
            records_per_pull=entity.records_per_pull,
            cursor_step_seconds=entity.cursor_step_seconds,
            velocity_mode=entity.velocity_mode.value,
            sample_blueprint=entity.sample_blueprint,
            inferred_json_schema=dict(entity.inferred_json_schema),
            chaos_policy=dict(entity.chaos_policy),
            version=entity.version,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
        except IntegrityError:
            logger.error(
                "simulator_entity_duplicate_conflict",
                sandbox_id=entity.sandbox_id,
                entity_name=entity.entity_name,
            )
            return Result.fail(
                DuplicateSimulatorEntityError.for_name(entity.sandbox_id, entity.entity_name)
            )
        return Result.ok(_entity_record_to_dto(record))

    async def update_entity(
        self, entity: SimulatorEntityDTO
    ) -> Result[SimulatorEntityDTO, IpError]:
        stmt = select(SimulatorEntityRecord).where(
            SimulatorEntityRecord.sandbox_id == entity.sandbox_id,
            SimulatorEntityRecord.id == entity.id,
        )
        record = (await self._session.execute(stmt)).scalar_one_or_none()
        if record is None:
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="entity_id",
                    message=f"Simulator entity '{entity.id}' does not exist.",
                )
            )
        try:
            async with self._session.begin_nested():
                _update_entity_record_from_dto(record, entity)
                await self._session.flush()
        except IntegrityError:
            logger.error(
                "simulator_entity_rename_conflict",
                sandbox_id=entity.sandbox_id,
                entity_name=entity.entity_name,
            )
            return Result.fail(
                DuplicateSimulatorEntityError.for_name(entity.sandbox_id, entity.entity_name)
            )
        return Result.ok(_entity_record_to_dto(record))

    async def delete_entity(self, sandbox_id: str, entity_id: str) -> bool:
        stmt = (
            delete(SimulatorEntityRecord)
            .where(
                SimulatorEntityRecord.sandbox_id == sandbox_id,
                SimulatorEntityRecord.id == entity_id,
            )
            .returning(SimulatorEntityRecord.id)
        )
        deleted_id = (await self._session.execute(stmt)).scalar_one_or_none()
        deleted = deleted_id is not None
        if deleted:
            await self._session.flush()
        return deleted


class SqlAlchemySimulatorUnitOfWork(BaseSqlAlchemyUnitOfWork, SimulatorUnitOfWorkPort):
    """Concrete SQLAlchemy Unit of Work managing atomic transactions for Virtual Sandboxes & Entities."""

    sandboxes: SimulatorRepositoryPort

    def __init__(self, global_session: AsyncSession) -> None:
        super().__init__(global_session)
        self.sandboxes = SqlAlchemySimulatorRepository(global_session)


class SqlAlchemySessionScopedSimulatorSandboxReader(SimulatorSandboxReaderPort):
    """Session-opening `SimulatorSandboxReaderPort` backed by `DatabaseRouterPort` or `DatabaseProvider`."""

    def __init__(
        self,
        *,
        db_router_getter: Callable[[], DatabaseRouterPort | None] | None = None,
        db_provider_getter: Callable[[], DatabaseProvider | None] | None = None,
    ) -> None:
        self._db_router_getter = db_router_getter
        self._db_provider_getter = db_provider_getter

    @contextlib.asynccontextmanager
    async def _open_session(self) -> AsyncIterator[AsyncSession | None]:
        db_router = self._db_router_getter() if self._db_router_getter is not None else None
        if db_router is not None:
            async with contextlib.aclosing(db_router.get_global_session()) as sessions:
                async for session in sessions:
                    yield session
                    return
        db_provider = self._db_provider_getter() if self._db_provider_getter is not None else None
        if db_provider is not None:
            async with db_provider.session() as provider_session:
                yield provider_session
                return
        yield None

    async def authenticate_sandbox(
        self,
        *,
        sandbox_id: str,
        raw_api_key: str,
    ) -> Result[SimulatorSandboxDTO, IpError]:
        async with self._open_session() as session:
            if session is None:
                return Result.fail(
                    InvalidConnectionConfigError(
                        field_name="sandbox_id",
                        message="Simulator database session is not initialized.",
                    )
                )
            return await SqlAlchemySimulatorRepository(session).authenticate_sandbox(
                sandbox_id=sandbox_id,
                raw_api_key=raw_api_key,
            )

    async def list_entities_by_sandbox(self, sandbox_id: str) -> Sequence[SimulatorEntityDTO]:
        async with self._open_session() as session:
            if session is None:
                return ()
            return await SqlAlchemySimulatorRepository(session).list_entities_by_sandbox(sandbox_id)

    async def get_entity_by_name(
        self, sandbox_id: str, entity_name: str
    ) -> SimulatorEntityDTO | None:
        async with self._open_session() as session:
            if session is None:
                return None
            return await SqlAlchemySimulatorRepository(session).get_entity_by_name(
                sandbox_id, entity_name
            )


class SqlAlchemySimulatorApiProvider(SimulatorApiProviderPort[AsyncSession]):
    """Production `SimulatorApiProviderPort` constructing SQLAlchemy UoW/readers from `AsyncSession`."""

    def create_uow(self, global_session: AsyncSession) -> SimulatorUnitOfWorkPort:
        return SqlAlchemySimulatorUnitOfWork(global_session)

    def get_sandbox_reader(self, global_session: AsyncSession) -> SimulatorSandboxReaderPort:
        return SqlAlchemySimulatorRepository(global_session)


__all__ = [
    "SqlAlchemySessionScopedSimulatorSandboxReader",
    "SqlAlchemySimulatorApiProvider",
    "SqlAlchemySimulatorRepository",
    "SqlAlchemySimulatorUnitOfWork",
]
