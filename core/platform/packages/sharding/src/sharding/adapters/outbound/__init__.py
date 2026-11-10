"""Outbound adapters for Multi-Tenant & Cellular Sharding."""

from sharding.adapters.outbound.database import SqlAlchemyShardTopologyRepository

__all__ = ["SqlAlchemyShardTopologyRepository"]
