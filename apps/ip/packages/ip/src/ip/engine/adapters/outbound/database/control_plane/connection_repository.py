"""SQLAlchemy repository adapter for Connection aggregates."""

from collections.abc import Sequence
from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.control_plane import ConnectionRecord
from ip.engine.domain.exceptions import DuplicateConnectionFingerprintError, Result
from ip.engine.domain.models.connection import AuthType, Connection, ConnectionStatus
from ip.engine.domain.types import JsonDict
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyConnectionRepository(GlobalSqlAlchemyRepository, ConnectionRepositoryPort):
    """PostgreSQL SQLAlchemy implementation of ConnectionRepositoryPort."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _parse_iso(iso_str: str | None) -> datetime | None:
        if not iso_str:
            return None
        return datetime.fromisoformat(iso_str)

    @staticmethod
    def _format_iso(dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return dt.isoformat()

    @classmethod
    def _to_domain_model(cls, record: ConnectionRecord) -> Connection:
        """Strict, explicit data mapper from Record to Domain model (No dynamic reflection)."""
        pub_config: JsonDict = dict(record.public_config) if record.public_config else {}
        connection = Connection(
            id=record.id,
            tenant_id=record.tenant_id,
            app_id=record.app_id,
            name=record.name,
            auth_type=AuthType(record.auth_type),
            public_config=pub_config,
            encrypted_credentials=record.encrypted_credentials,
            key_encryption_version=record.key_encryption_version,
            connection_fingerprint=record.connection_fingerprint,
            status=ConnectionStatus(record.status),
            token_expires_at=cls._format_iso(record.token_expires_at),
            last_refreshed_at=cls._format_iso(record.last_refreshed_at),
            last_error_code=record.last_error_code,
            last_error_message=record.last_error_message,
            created_at=record.created_at.isoformat(),
            updated_at=record.updated_at.isoformat(),
            deactivated_at=cls._format_iso(record.deactivated_at),
        )
        return connection

    @classmethod
    def _update_record_from_domain(cls, record: ConnectionRecord, domain: Connection) -> None:
        """Strict, explicit data mapper updating Record properties from Domain (No dynamic reflection)."""
        record.name = domain.name
        record.auth_type = domain.auth_type.value
        record.public_config = dict(domain.public_config)
        record.encrypted_credentials = domain.encrypted_credentials
        record.key_encryption_version = domain.key_encryption_version
        record.connection_fingerprint = domain.connection_fingerprint
        record.status = domain.status.value
        record.token_expires_at = cls._parse_iso(domain.token_expires_at)
        record.last_refreshed_at = cls._parse_iso(domain.last_refreshed_at)
        record.last_error_code = domain.last_error_code
        record.last_error_message = domain.last_error_message
        record.updated_at = cls._parse_iso(domain.updated_at) or datetime.now(UTC)
        record.deactivated_at = cls._parse_iso(domain.deactivated_at)

    async def save(
        self, connection: Connection
    ) -> Result[Connection, DuplicateConnectionFingerprintError]:
        """Saves or updates a Connection aggregate and drains domain events."""
        stmt = select(ConnectionRecord).where(ConnectionRecord.id == connection.id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if record is None:
            record = ConnectionRecord(
                id=connection.id,
                tenant_id=connection.tenant_id,
                app_id=connection.app_id,
                name=connection.name,
                auth_type=connection.auth_type.value,
                public_config=dict(connection.public_config),
                encrypted_credentials=connection.encrypted_credentials,
                key_encryption_version=connection.key_encryption_version,
                connection_fingerprint=connection.connection_fingerprint,
                status=connection.status.value,
                token_expires_at=self._parse_iso(connection.token_expires_at),
                last_refreshed_at=self._parse_iso(connection.last_refreshed_at),
                last_error_code=connection.last_error_code,
                last_error_message=connection.last_error_message,
                created_at=self._parse_iso(connection.created_at) or datetime.now(UTC),
                updated_at=self._parse_iso(connection.updated_at) or datetime.now(UTC),
                deactivated_at=self._parse_iso(connection.deactivated_at),
            )
            self._session.add(record)
        else:
            self._update_record_from_domain(record, connection)

        self._drain_events(connection, default_tenant_id=connection.tenant_id)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if "uq_tenant_active_fingerprint" in str(exc):
                return Result.fail(
                    DuplicateConnectionFingerprintError.create(
                        tenant_id=connection.tenant_id,
                        app_id=connection.app_id,
                        fingerprint=connection.connection_fingerprint,
                    )
                )
            raise

        return Result.ok(connection)

    async def get_by_id(self, connection_id: str) -> Connection | None:
        stmt = select(ConnectionRecord).where(ConnectionRecord.id == connection_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain_model(record)

    async def get_by_fingerprint(
        self,
        tenant_id: str,
        fingerprint: str,
    ) -> Connection | None:
        stmt = select(ConnectionRecord).where(
            ConnectionRecord.tenant_id == tenant_id,
            ConnectionRecord.connection_fingerprint == fingerprint,
            ConnectionRecord.status != ConnectionStatus.DEACTIVATED.value,
        )
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain_model(record)

    async def list_by_tenant(
        self,
        tenant_id: str,
        status: ConnectionStatus | None = None,
    ) -> Sequence[Connection]:
        stmt = select(ConnectionRecord).where(ConnectionRecord.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(ConnectionRecord.status == status.value)
        stmt = stmt.order_by(ConnectionRecord.created_at.desc())
        result = await self._session.execute(stmt)
        return [self._to_domain_model(r) for r in result.scalars().all()]
