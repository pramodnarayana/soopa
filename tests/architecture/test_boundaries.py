import pytest
from pytest_archon import archrule


def test_domain_layer_isolation():
    """
    Enforce that the domain layer does NOT import from infrastructure,
    adapters, api, or third-party frameworks like FastAPI/SQLAlchemy.
    """
    (
        archrule("domain_is_pure")
        .match("notification.domain*")
        .should_not_import("notification.adapters*")
        .should_not_import("notification.api*")
        .should_not_import("sqlalchemy*")
        .should_not_import("fastapi*")
        .should_not_import("asyncpg*")
        .check("notification")
    )


@pytest.mark.skip(reason="Next Ticket: Enable Architecture Boundary Enforcement")
def test_modular_monolith_strict_isolation():
    """
    Enforce that separate bounded contexts do not import from each other directly.
    For example, Notification Engine must not import from Scheduler Engine.
    They should communicate via Outbox events.
    """
    (
        archrule("notification_is_isolated")
        .match("notification.*")
        .should_not_import("scheduler_engine.*")
        .should_not_import("edi.*")
        .check("core")
    )
