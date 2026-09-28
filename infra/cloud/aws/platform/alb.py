from infra_seedwork.network import provision_alb


def provision_load_balancer(prefix: str, subnets: list, sg_id: str, tags: dict, cert_arn=None):
    main_alb, main_listener, obs_listener = provision_alb(
        name=f"{prefix}main",
        subnets=subnets,
        security_group_id=sg_id,
        tags=tags,
        certificate_arn=cert_arn,
    )
    return main_alb, main_listener, obs_listener
