"""SQLAlchemy repository adapter for Connection aggregates."""

from collections.abc import Sequence
from datetime import UTC, datetime

from database.outbox_serializer import serialize_domain_event
from ip.adapters.outbound.database.models.connection_model import ConnectionRecord
from ip.adapters.outbound.database.models.outbox_model import IpOutboxRecord
from ip.domain.models.connection import AuthType, Connection, ConnectionStatus
from ip.domain.types import JsonDict
from ip.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from outbox.domain.constants import OutboxStatus
from seedwork.utils import generate_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyConnectionRepository(ConnectionRepositoryPort):
    """PostgreSQL SQLAlchemy implementation of ConnectionRepositoryPort."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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

    def _to_domain_model(self, record: ConnectionRecord) -> Connection:
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
            token_expires_at=self._format_iso(record.token_expires_at),
            last_refreshed_at=self._format_iso(record.last_refreshed_at),
            last_error_code=record.last_error_code,
            last_error_message=record.last_error_message,
            created_at=record.created_at.isoformat(),
            updated_at=record.updated_at.isoformat(),
            deactivated_at=self._format_iso(record.deactivated_at),
        )
        return connection

    def _update_record_from_domain(self, record: ConnectionRecord, domain: Connection) -> None:
        """Strict, explicit data mapper updating Record properties from Domain (No dynamic reflection)."""
        record.name = domain.name
        record.auth_type = domain.auth_type.value
        record.public_config = dict(domain.public_config)
        record.encrypted_credentials = domain.encrypted_credentials
        record.key_encryption_version = domain.key_encryption_version
        record.connection_fingerprint = domain.connection_fingerprint
        record.status = domain.status.value
        record.token_expires_at = self._parse_iso(domain.token_expires_at)
        record.last_refreshed_at = self._parse_iso(domain.last_refreshed_at)
        record.last_error_code = domain.last_error_code
        record.last_error_message = domain.last_error_message
        record.updated_at = self._parse_iso(domain.updated_at) or datetime.now(UTC)
        record.deactivated_at = self._parse_iso(domain.deactivated_at)

    def _drain_events(self, connection: Connection) -> None:
        """Extracts aggregate domain events and stages them into the transactional outbox."""
        for event in connection.domain_events:
            outbox_id = generate_id(IpOutboxRecord.ID_PREFIX)
            event_name = event.event_name
            payload_dict = serialize_domain_event(event)
            tenant_id = event.get_routing_tenant_id() or connection.tenant_id

            outbox_event = IpOutboxRecord(
                id=outbox_id,
                idempotency_key=event.idempotency_key,
                tenant_id=tenant_id,
                event_type=event_name,
                payload=payload_dict,
                status=OutboxStatus.PENDING,
            )
            self._session.add(outbox_event)

        connection.clear_domain_events()

    async def save(self, connection: Connection) -> None:
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

        self._drain_events(connection)
        await self._session.flush()

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
