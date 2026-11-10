"""Adapters layer for Multi-Tenant & Cellular Sharding."""

from sharding.adapters.outbound import SqlAlchemyShardTopologyRepository

__all__ = ["SqlAlchemyShardTopologyRepository"]
