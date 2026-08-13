from pytest_archon import archrule


def test_ucp_domain_is_isolated():
    """
    Enforce that UCP Domain Bounded Context is completely isolated from Adapters and Application layers.
    Domain logic must have ZERO external dependencies.
    """
    (
        archrule("UCP Domain Isolation")
        .match("core.ucp.packages.ucp.src.ucp.domain*")
        .should_not_import("core.ucp.packages.ucp.src.ucp.adapters*")
        .should_not_import("core.ucp.packages.ucp.src.ucp.application*")
        .check("core.ucp.packages.ucp.src.ucp")
    )


def test_edi_domain_is_isolated():
    """
    Enforce that EDI Domain Bounded Context is isolated from Adapters and external boundaries.
    """
    (
        archrule("EDI Domain Isolation")
        .match("apps.edi.packages.domain*")
        .should_not_import("apps.edi.packages.database*")
        .should_not_import("apps.edi.packages.pipeline*")
        .check("apps.edi.packages")
    )


def test_no_cross_module_pollution():
    """
    Enforce Modular Monolith constraints: UCP and EDI cannot import each other's adapters directly.
    """
    (
        archrule("Modular Monolith Isolation")
        .match("core.ucp.packages.ucp.src.ucp.adapters*")
        .should_not_import("apps.edi.packages.database*")
        .should_not_import("apps.edi.apps.edi-worker.orchestrator.src.worker.adapters*")
        .check("core.ucp.packages.ucp.src.ucp")
    )
