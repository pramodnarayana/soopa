"""Zero-mock pure domain unit tests for ISA pair -> tenant resolution rules."""

from __future__ import annotations

from edi.domain.routing.isa_resolution import (
    IsaResolutionStatus,
    IsaRouteCandidate,
    resolve_isa_candidates,
)

_PLATFORM = "ten_000000000000000000000000"


def test_empty_candidates_returns_not_found() -> None:
    res = resolve_isa_candidates([], platform_tenant_id=_PLATFORM)
    assert res.status == IsaResolutionStatus.NOT_FOUND
    assert res.tenant_id is None


def test_single_active_customer_route_returns_active() -> None:
    res = resolve_isa_candidates(
        [
            IsaRouteCandidate(
                route_id="rt_1",
                tenant_id="iam_ten_a",
                name="Logiflow To Greatlakes",
                active=True,
            )
        ],
        platform_tenant_id=_PLATFORM,
    )
    assert res.status == IsaResolutionStatus.ACTIVE
    assert res.tenant_id == "iam_ten_a"


def test_active_route_takes_precedence_over_inactive_routes() -> None:
    res = resolve_isa_candidates(
        [
            IsaRouteCandidate(route_id="rt_old", tenant_id="iam_ten_old", name="Old", active=False),
            IsaRouteCandidate(route_id="rt_new", tenant_id="iam_ten_new", name="New", active=True),
        ],
        platform_tenant_id=_PLATFORM,
    )
    assert res.status == IsaResolutionStatus.ACTIVE
    assert res.tenant_id == "iam_ten_new"


def test_single_tenant_inactive_routes_returns_inactive_with_owner_and_names() -> None:
    res = resolve_isa_candidates(
        [
            IsaRouteCandidate(
                route_id="rt_2",
                tenant_id="iam_ten_a",
                name="Route B",
                active=False,
            ),
            IsaRouteCandidate(
                route_id="rt_1",
                tenant_id="iam_ten_a",
                name="Route A",
                active=False,
            ),
        ],
        platform_tenant_id=_PLATFORM,
    )
    assert res.status == IsaResolutionStatus.INACTIVE
    assert res.tenant_id == "iam_ten_a"
    assert res.inactive_route_ids == ("rt_1", "rt_2")
    assert res.inactive_route_names == ("Route A", "Route B")


def test_multiple_active_tenants_returns_ambiguous() -> None:
    res = resolve_isa_candidates(
        [
            IsaRouteCandidate(route_id="rt_1", tenant_id="iam_ten_b", name="B", active=True),
            IsaRouteCandidate(route_id="rt_2", tenant_id="iam_ten_a", name="A", active=True),
        ],
        platform_tenant_id=_PLATFORM,
    )
    assert res.status == IsaResolutionStatus.AMBIGUOUS
    assert res.tenant_id is None
    assert res.matched_tenant_ids == ("iam_ten_a", "iam_ten_b")


def test_multiple_inactive_tenants_returns_ambiguous() -> None:
    res = resolve_isa_candidates(
        [
            IsaRouteCandidate(route_id="rt_1", tenant_id="iam_ten_b", name="B", active=False),
            IsaRouteCandidate(route_id="rt_2", tenant_id="iam_ten_a", name="A", active=False),
        ],
        platform_tenant_id=_PLATFORM,
    )
    assert res.status == IsaResolutionStatus.AMBIGUOUS
    assert res.tenant_id is None
    assert res.matched_tenant_ids == ("iam_ten_a", "iam_ten_b")


def test_platform_sentinel_only_routes_return_platform_only() -> None:
    for is_active in (True, False):
        res = resolve_isa_candidates(
            [
                IsaRouteCandidate(
                    route_id="rt_plat",
                    tenant_id=_PLATFORM,
                    name="Platform",
                    active=is_active,
                )
            ],
            platform_tenant_id=_PLATFORM,
        )
        assert res.status == IsaResolutionStatus.PLATFORM_ONLY
        assert res.tenant_id is None


def test_transaction_type_filtering_prevents_cross_transaction_false_active() -> None:
    candidates = [
        IsaRouteCandidate(
            route_id="rt_850",
            tenant_id="iam_ten_a",
            name="Inbound 850",
            active=False,
            transaction_type="850",
        ),
        IsaRouteCandidate(
            route_id="rt_810",
            tenant_id="iam_ten_a",
            name="Inbound 810",
            active=True,
            transaction_type="810",
        ),
    ]

    res_850 = resolve_isa_candidates(
        candidates, platform_tenant_id=_PLATFORM, transaction_type="850"
    )
    assert res_850.status == IsaResolutionStatus.INACTIVE
    assert res_850.tenant_id == "iam_ten_a"
    assert res_850.inactive_route_ids == ("rt_850",)
    assert res_850.inactive_route_names == ("Inbound 850",)

    res_810 = resolve_isa_candidates(
        candidates, platform_tenant_id=_PLATFORM, transaction_type="810"
    )
    assert res_810.status == IsaResolutionStatus.ACTIVE
    assert res_810.tenant_id == "iam_ten_a"

    res_856 = resolve_isa_candidates(
        candidates, platform_tenant_id=_PLATFORM, transaction_type="856"
    )
    assert res_856.status == IsaResolutionStatus.NOT_FOUND


def test_wildcard_transaction_type_matches_any_transaction_set() -> None:
    res = resolve_isa_candidates(
        [
            IsaRouteCandidate(
                route_id="rt_any",
                tenant_id="iam_ten_a",
                name="Wildcard Route",
                active=True,
                transaction_type=None,
            )
        ],
        platform_tenant_id=_PLATFORM,
        transaction_type="850",
    )
    assert res.status == IsaResolutionStatus.ACTIVE
    assert res.tenant_id == "iam_ten_a"
