import pytest
from pytest_archon import archrule

# TODO (Next Ticket): Enable Architecture Boundary Enforcement
# This test ensures that our Hexagonal Architecture / Modular Monolith rules are strictly followed.
# Specifically, we guarantee that the 'domain' layer never imports from 'adapters' or external APIs,
# keeping our core business logic pure and decoupled from infrastructure.


@pytest.mark.skip(reason="Next Ticket: Enable Architecture Boundary Enforcement")
def test_domain_layer_isolation():
    """
    Enforce that the domain layer does NOT import from infrastructure,
    adapters, api, or third-party frameworks like FastAPI/SQLAlchemy.
    """
    (
        archrule("domain_is_pure")
        .match("*.domain.*")
        .should_not_import("*.adapters.*")
        .should_not_import("*.api.*")
        .should_not_import("sqlalchemy")
        .should_not_import("fastapi")
        .should_not_import("asyncpg")
        .check("soopa_mono")  # Replace with the actual top-level package if needed
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
        .match("notification_engine.*")
        .should_not_import("scheduler_engine.*")
        .should_not_import("edi.*")
        .check("core")
    )
