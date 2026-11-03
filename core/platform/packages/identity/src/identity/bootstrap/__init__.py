"""Composition root factories for the Identity bounded context."""

from identity.bootstrap.uow_factory import create_identity_uow

__all__ = ["create_identity_uow"]
