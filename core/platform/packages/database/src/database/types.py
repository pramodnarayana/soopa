from typing import NewType

from sqlalchemy.ext.asyncio import AsyncSession

# Strongly typed sessions to prevent cross-plane and cross-CQRS contamination at compile time.
# GlobalSession is strictly for Control Plane operations.
# TenantSession is strictly for Data Plane Primary Writer (Command / UnitOfWork) operations.
# TenantReadSession is strictly for Data Plane Read Replica (Query-only) operations.
GlobalSession = NewType("GlobalSession", AsyncSession)
TenantSession = NewType("TenantSession", AsyncSession)
TenantReadSession = NewType("TenantReadSession", AsyncSession)

# Monotonic 64-bit causal database replication watermark (e.g., byte offset from 0/0).
ReplicationWatermark = NewType("ReplicationWatermark", int)
