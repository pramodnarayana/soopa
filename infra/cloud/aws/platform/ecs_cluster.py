import pulumi_aws as aws
from constants import EcsConstants


def provision_cluster(prefix: str, tags: dict, vpc_id: str):
    # Provision a Private DNS Namespace for internal service discovery
    namespace = aws.servicediscovery.PrivateDnsNamespace(
        f"{prefix}namespace",
        name=f"{prefix}cluster.local",
        description="Private DNS namespace for internal ECS service discovery",
        vpc=vpc_id,
        tags=tags,
    )

    ecs_cluster = aws.ecs.Cluster(
        f"{prefix}cluster",
        name=f"{prefix}cluster",
        tags=tags,
    )

    # Configure Fargate Capacity Providers
    aws.ecs.ClusterCapacityProviders(
        f"{prefix}cluster-cp",
        cluster_name=ecs_cluster.name,
        capacity_providers=[EcsConstants.CAPACITY_PROVIDER, "FARGATE_SPOT"],
        default_capacity_provider_strategies=[
            aws.ecs.ClusterCapacityProvidersDefaultCapacityProviderStrategyArgs(
                capacity_provider=EcsConstants.CAPACITY_PROVIDER,
                weight=1,
                base=1,
            )
        ],
    )

    return ecs_cluster, namespace
