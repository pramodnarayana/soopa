"""SQLAlchemy repository adapter for ConnectionCatalog aggregates."""

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.control_plane import ConnectionCatalogRecord
from ip.engine.domain.models.catalog import (
    ConnectionCatalog,
    StreamField,
    StreamSchema,
    SyncMode,
)
from ip.engine.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from seedwork.domain.types import JsonDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyCatalogRepository(GlobalSqlAlchemyRepository, CatalogRepositoryPort):
    """PostgreSQL SQLAlchemy implementation of CatalogRepositoryPort."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _parse_iso(iso_str: str | None) -> datetime:
        if not iso_str:
            return datetime.now(UTC)
        return datetime.fromisoformat(iso_str)

    @classmethod
    def _to_domain_model(cls, record: ConnectionCatalogRecord) -> ConnectionCatalog:
        raw_streams = record.schema_definition.get("streams", [])
        streams: list[StreamSchema] = []

        if isinstance(raw_streams, list):
            for s in raw_streams:
                if not isinstance(s, dict):
                    continue
                raw_fields = s.get("fields", [])
                fields: list[StreamField] = []
                if isinstance(raw_fields, list):
                    for f in raw_fields:
                        if isinstance(f, dict):
                            fields.append(
                                StreamField(
                                    name=str(f["name"]),
                                    data_type=str(f["data_type"]),
                                    nullable=bool(f.get("nullable", True)),
                                    description=(
                                        str(f["description"])
                                        if f.get("description") is not None
                                        else None
                                    ),
                                )
                            )
                raw_modes = s.get("supported_sync_modes", ["FULL_REFRESH", "INCREMENTAL"])
                sync_modes = (
                    [SyncMode(str(m)) for m in raw_modes if isinstance(m, str)]
                    if isinstance(raw_modes, list)
                    else [SyncMode.FULL_REFRESH, SyncMode.INCREMENTAL]
                )
                raw_pk = s.get("primary_key", [])
                pk_list = [str(k) for k in raw_pk] if isinstance(raw_pk, list) else []
                cursor = str(s["cursor_field"]) if s.get("cursor_field") is not None else None
                streams.append(
                    StreamSchema(
                        name=str(s["name"]),
                        fields=fields,
                        primary_key=pk_list,
                        cursor_field=cursor,
                        supported_sync_modes=sync_modes,
                    )
                )

        return ConnectionCatalog(
            id=record.id,
            connection_id=record.connection_id,
            catalog_version=record.catalog_version,
            catalog_hash=record.catalog_hash,
            streams=streams,
            is_active=record.is_active,
            discovered_at=record.discovered_at.isoformat(),
        )

    @classmethod
    def _serialize_schema_definition(cls, catalog: ConnectionCatalog) -> JsonDict:
        return {
            "streams": [
                {
                    "name": s.name,
                    "fields": [
                        {
                            "name": f.name,
                            "data_type": f.data_type,
                            "nullable": f.nullable,
                            "description": f.description,
                        }
                        for f in s.fields
                    ],
                    "primary_key": list(s.primary_key),
                    "cursor_field": s.cursor_field,
                    "supported_sync_modes": [m.value for m in s.supported_sync_modes],
                }
                for s in catalog.streams
            ]
        }

    async def save(self, catalog: ConnectionCatalog) -> None:
        """Saves a new catalog version into the repository."""
        record = ConnectionCatalogRecord(
            id=catalog.id,
            connection_id=catalog.connection_id,
            catalog_version=catalog.catalog_version,
            catalog_hash=catalog.catalog_hash,
            schema_definition=self._serialize_schema_definition(catalog),
            is_active=catalog.is_active,
            discovered_at=self._parse_iso(catalog.discovered_at),
        )
        self._session.add(record)
        self._drain_events(catalog)
        await self._session.flush()

    async def get_active_by_connection_id(
        self,
        connection_id: str,
    ) -> ConnectionCatalog | None:
        stmt = (
            select(ConnectionCatalogRecord)
            .where(
                ConnectionCatalogRecord.connection_id == connection_id,
                ConnectionCatalogRecord.is_active.is_(True),
            )
            .order_by(ConnectionCatalogRecord.catalog_version.desc())
        )
        result = await self._session.execute(stmt)
        record = result.scalars().first()
        if record is None:
            return None
        return self._to_domain_model(record)

    async def get_by_version(
        self,
        connection_id: str,
        version: int,
    ) -> ConnectionCatalog | None:
        stmt = select(ConnectionCatalogRecord).where(
            ConnectionCatalogRecord.connection_id == connection_id,
            ConnectionCatalogRecord.catalog_version == version,
        )
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain_model(record)
