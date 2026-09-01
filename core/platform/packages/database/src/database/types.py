from typing import NewType

from sqlalchemy.ext.asyncio import AsyncSession

# Strongly typed sessions to prevent cross-plane database contamination.
# GlobalSession is strictly for Control Plane operations.
# TenantSession is strictly for Data Plane (Shard) operations.
GlobalSession = NewType("GlobalSession", AsyncSession)
TenantSession = NewType("TenantSession", AsyncSession)
