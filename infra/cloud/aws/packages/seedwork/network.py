import pulumi_aws as aws


def provision_alb(
    name: str,
    subnets: list,
    security_group_id: str,
    tags: dict,
    internal: bool = False,
    certificate_arn: str = None,
) -> tuple[aws.lb.LoadBalancer, aws.lb.Listener, aws.lb.Listener]:
    """
    Provisions an Application Load Balancer and a default port 80 listener.
    """
    alb = aws.lb.LoadBalancer(
        f"{name}-alb",
        name=name,
        internal=internal,
        load_balancer_type="application",
        security_groups=[security_group_id],
        subnets=subnets,
        tags=tags,
    )

    listener = aws.lb.Listener(
        f"{name}-http-listener",
        load_balancer_arn=alb.arn,
        port=80,
        protocol="HTTP",
        default_actions=[
            aws.lb.ListenerDefaultActionArgs(
                type="redirect",
                redirect=aws.lb.ListenerDefaultActionRedirectArgs(
                    port="443",
                    protocol="HTTPS",
                    status_code="HTTP_301",
                ),
            )
        ],
        tags=tags,
    )

    app_listener = listener
    if certificate_arn:
        app_listener = aws.lb.Listener(
            f"{name}-https-listener",
            load_balancer_arn=alb.arn,
            port=443,
            protocol="HTTPS",
            ssl_policy="ELBSecurityPolicy-2016-08",
            certificate_arn=certificate_arn,
            default_actions=[
                aws.lb.ListenerDefaultActionArgs(
                    type="fixed-response",
                    fixed_response=aws.lb.ListenerDefaultActionFixedResponseArgs(
                        content_type="text/plain",
                        message_body="404: Not Found",
                        status_code="404",
                    ),
                )
            ],
            tags=tags,
        )

    observability_listener = aws.lb.Listener(
        f"{name}-obs-listener",
        load_balancer_arn=alb.arn,
        port=5080,
        protocol="HTTP",
        default_actions=[
            aws.lb.ListenerDefaultActionArgs(
                type="fixed-response",
                fixed_response=aws.lb.ListenerDefaultActionFixedResponseArgs(
                    content_type="text/plain",
                    message_body="404: Not Found",
                    status_code="404",
                ),
            )
        ],
        tags=tags,
    )

    return alb, app_listener, observability_listener


def provision_target_group_and_rule(
    name: str,
    vpc_id: str,
    listener_arn: str,
    priority: int,
    path_pattern: str,
    tags: dict,
    port: int = 8000,
) -> aws.lb.TargetGroup:
    """
    Provisions a Target Group for ECS Fargate and attaches it to the Listener with a path rule.
    """
    tg = aws.lb.TargetGroup(
        f"{name}-tg",
        name=name,
        port=port,
        protocol="HTTP",
        vpc_id=vpc_id,
        target_type="ip",
        health_check=aws.lb.TargetGroupHealthCheckArgs(
            path="/health",
            interval=30,
            timeout=5,
            healthy_threshold=2,
            unhealthy_threshold=3,
        ),
        tags=tags,
    )

    aws.lb.ListenerRule(
        f"{name}-rule",
        listener_arn=listener_arn,
        priority=priority,
        actions=[
            aws.lb.ListenerRuleActionArgs(
                type="forward",
                target_group_arn=tg.arn,
            )
        ],
        conditions=[
            aws.lb.ListenerRuleConditionArgs(
                path_pattern=aws.lb.ListenerRuleConditionPathPatternArgs(
                    values=[path_pattern],
                )
            )
        ],
        tags=tags,
    )

    return tg
