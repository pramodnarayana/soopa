from __future__ import annotations

from collections.abc import Sequence

import pulumi
from infra_seedwork.network import AlbResources, provision_alb


def provision_load_balancer(
    prefix: str,
    subnets: Sequence[pulumi.Input[str]],
    sg_id: pulumi.Input[str],
    tags: dict[str, str],
    cert_arn: pulumi.Input[str] | None = None,
) -> AlbResources:
    return provision_alb(
        name=f"{prefix}main",
        subnets=subnets,
        security_group_id=sg_id,
        tags=tags,
        certificate_arn=cert_arn,
    )
