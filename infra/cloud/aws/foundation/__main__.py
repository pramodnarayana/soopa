"""
Foundation Layer (Layer 1)
==========================
Provisions the highly stable VPC, subnets, NAT Gateway, and core Security Groups.
This layer changes very rarely.
"""

import pulumi
import pulumi_aws as aws

_env = pulumi.get_stack()
_prefix = f"{_env}-"

_TAGS = {"ManagedBy": "pulumi", "Component": "foundation", "Environment": _env}

_region = aws.get_region()

vpc = aws.ec2.Vpc(
    f"{_prefix}vpc",
    cidr_block="10.0.0.0/16",
    enable_dns_hostnames=True,
    enable_dns_support=True,
    tags={**_TAGS, "Name": f"{_prefix}vpc"},
)

igw = aws.ec2.InternetGateway(
    f"{_prefix}igw",
    vpc_id=vpc.id,
    tags={**_TAGS, "Name": f"{_prefix}igw"},
)

# ── Public subnets ────────────────────────────────────────────────────────────
public_subnet_a = aws.ec2.Subnet(
    f"{_prefix}public-subnet-a",
    vpc_id=vpc.id,
    cidr_block="10.0.0.0/24",
    availability_zone=f"{_region.name}a",
    map_public_ip_on_launch=True,
    tags={**_TAGS, "Name": f"{_prefix}public-a"},
)
public_subnet_b = aws.ec2.Subnet(
    f"{_prefix}public-subnet-b",
    vpc_id=vpc.id,
    cidr_block="10.0.1.0/24",
    availability_zone=f"{_region.name}b",
    map_public_ip_on_launch=True,
    tags={**_TAGS, "Name": f"{_prefix}public-b"},
)

public_rt = aws.ec2.RouteTable(
    f"{_prefix}public-rt",
    vpc_id=vpc.id,
    routes=[aws.ec2.RouteTableRouteArgs(cidr_block="0.0.0.0/0", gateway_id=igw.id)],
    tags={**_TAGS, "Name": f"{_prefix}public-rt"},
)
aws.ec2.RouteTableAssociation(
    f"{_prefix}public-rta-a", subnet_id=public_subnet_a.id, route_table_id=public_rt.id
)
aws.ec2.RouteTableAssociation(
    f"{_prefix}public-rta-b", subnet_id=public_subnet_b.id, route_table_id=public_rt.id
)

# ── NAT Gateway ───────────────────────────────────────────────────────────────
eip = aws.ec2.Eip(f"{_prefix}nat-eip", domain="vpc", tags={**_TAGS, "Name": f"{_prefix}nat-eip"})
nat_gw = aws.ec2.NatGateway(
    f"{_prefix}nat-gw",
    subnet_id=public_subnet_a.id,
    allocation_id=eip.id,
    tags={**_TAGS, "Name": f"{_prefix}nat-gw"},
)

# ── Private subnets ───────────────────────────────────────────────────────────
private_subnet_a = aws.ec2.Subnet(
    f"{_prefix}private-subnet-a",
    vpc_id=vpc.id,
    cidr_block="10.0.10.0/24",
    availability_zone=f"{_region.name}a",
    tags={**_TAGS, "Name": f"{_prefix}private-a"},
)
private_subnet_b = aws.ec2.Subnet(
    f"{_prefix}private-subnet-b",
    vpc_id=vpc.id,
    cidr_block="10.0.11.0/24",
    availability_zone=f"{_region.name}b",
    tags={**_TAGS, "Name": f"{_prefix}private-b"},
)

private_rt = aws.ec2.RouteTable(
    f"{_prefix}private-rt",
    vpc_id=vpc.id,
    routes=[aws.ec2.RouteTableRouteArgs(cidr_block="0.0.0.0/0", nat_gateway_id=nat_gw.id)],
    tags={**_TAGS, "Name": f"{_prefix}private-rt"},
)
aws.ec2.RouteTableAssociation(
    f"{_prefix}private-rta-a", subnet_id=private_subnet_a.id, route_table_id=private_rt.id
)
aws.ec2.RouteTableAssociation(
    f"{_prefix}private-rta-b", subnet_id=private_subnet_b.id, route_table_id=private_rt.id
)

# ── Security Groups ───────────────────────────────────────────────────────────
main_alb_sg = aws.ec2.SecurityGroup(
    f"{_prefix}main-alb-sg",
    vpc_id=vpc.id,
    description="ALB: accepts HTTPS + HTTP-redirect from internet, forwards to app containers",
    ingress=[
        aws.ec2.SecurityGroupIngressArgs(
            description="HTTPS from internet",
            from_port=443,
            to_port=443,
            protocol="tcp",
            cidr_blocks=["0.0.0.0/0"],
        ),
        aws.ec2.SecurityGroupIngressArgs(
            description="HTTP (redirect to HTTPS)",
            from_port=80,
            to_port=80,
            protocol="tcp",
            cidr_blocks=["0.0.0.0/0"],
        ),
        aws.ec2.SecurityGroupIngressArgs(
            description="OpenObserve UI",
            from_port=5080,
            to_port=5080,
            protocol="tcp",
            cidr_blocks=["0.0.0.0/0"],
        ),
    ],
    egress=[
        aws.ec2.SecurityGroupEgressArgs(
            description="Forward to ECS containers on app port 8000",
            from_port=8000,
            to_port=8000,
            protocol="tcp",
            cidr_blocks=["10.0.0.0/16"],
        ),
        aws.ec2.SecurityGroupEgressArgs(
            description="Forward to ECS containers on app port 5080 (OpenObserve)",
            from_port=5080,
            to_port=5080,
            protocol="tcp",
            cidr_blocks=["10.0.0.0/16"],
        ),
    ],
    tags={**_TAGS, "Name": f"{_prefix}main-alb-sg"},
)

app_sg = aws.ec2.SecurityGroup(
    f"{_prefix}app-sg",
    vpc_id=vpc.id,
    description="ECS tasks: accept from ALB only, allow all egress via NAT",
    ingress=[
        aws.ec2.SecurityGroupIngressArgs(
            description="Traffic from ALB only",
            from_port=8000,
            to_port=8000,
            protocol="tcp",
            source_security_group_id=main_alb_sg.id,
        ),
        aws.ec2.SecurityGroupIngressArgs(
            description="Traffic from ALB only (OpenObserve)",
            from_port=5080,
            to_port=5080,
            protocol="tcp",
            source_security_group_id=main_alb_sg.id,
        ),
    ],
    egress=[
        aws.ec2.SecurityGroupEgressArgs(
            description="All outbound — SQS/SNS/ECR/SecretsManager via NAT Gateway",
            from_port=0,
            to_port=0,
            protocol="-1",
            cidr_blocks=["0.0.0.0/0"],
        )
    ],
    tags={**_TAGS, "Name": f"{_prefix}app-sg"},
)

db_sg = aws.ec2.SecurityGroup(
    f"{_prefix}db-sg",
    vpc_id=vpc.id,
    description="RDS Database: accepts traffic from app containers",
    ingress=[
        aws.ec2.SecurityGroupIngressArgs(
            description="PostgreSQL from app SG",
            from_port=5432,
            to_port=5432,
            protocol="tcp",
            source_security_group_id=app_sg.id,
        )
    ],
    egress=[],
    tags={**_TAGS, "Name": f"{_prefix}db-sg"},
)

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("vpc_id", vpc.id)
pulumi.export("public_subnet_a_id", public_subnet_a.id)
pulumi.export("public_subnet_b_id", public_subnet_b.id)
pulumi.export("private_subnet_a_id", private_subnet_a.id)
pulumi.export("private_subnet_b_id", private_subnet_b.id)
pulumi.export("main_alb_sg_id", main_alb_sg.id)
pulumi.export("app_sg_id", app_sg.id)
pulumi.export("db_sg_id", db_sg.id)
