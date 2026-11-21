"""Legacy compatibility alias for SqlAlchemyReplayLedgerRepository."""

from ip.engine.adapters.outbound.database.data_plane.replay_ledger_repository import (
    SqlAlchemyReplayLedgerRepository,
)

SqlAlchemyReplayAuditRepository = SqlAlchemyReplayLedgerRepository

__all__ = ["SqlAlchemyReplayAuditRepository", "SqlAlchemyReplayLedgerRepository"]
