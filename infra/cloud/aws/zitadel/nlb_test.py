import pulumi_aws as aws

nlb = aws.lb.LoadBalancer(
    "zitadel-nlb",
    internal=False,
    load_balancer_type="network",
    subnets=["subnet-0ff69da6a8a36c641"],  # Need to pass public subnets
)
