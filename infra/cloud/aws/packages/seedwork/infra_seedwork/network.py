from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

import pulumi
import pulumi_aws as aws

from infra_seedwork.constants import NetworkConstants

_RFC1123_DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_ACM_DOMAIN_NAME_PATTERN = re.compile(
    r"^(?:\*\.)?[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)


@dataclass(frozen=True)
class AlbResources:
    """Strongly-typed bundle of provisioned ALB and listener resources."""

    load_balancer: aws.lb.LoadBalancer
    http_listener: aws.lb.Listener
    app_listener: aws.lb.Listener
    observability_listener: aws.lb.Listener


@dataclass(frozen=True)
class SniCertificateResources:
    """Strongly-typed bundle of provisioned ACM SNI certificate resources."""

    certificate: aws.acm.Certificate
    validation: aws.acm.CertificateValidation
    listener_certificate: aws.lb.ListenerCertificate

    @property
    def certificate_arn(self) -> pulumi.Output[str]:
        return self.validation.certificate_arn


def provision_alb(
    name: str,
    subnets: Sequence[pulumi.Input[str]],
    security_group_id: pulumi.Input[str],
    tags: dict[str, str],
    internal: bool = False,
    certificate_arn: pulumi.Input[str] | None = None,
) -> AlbResources:
    """
    Provisions an Application Load Balancer with HTTP (port 80), optional HTTPS (port 443),
    and observability (port 5080) listeners.
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

    if certificate_arn:
        # HTTP redirects to HTTPS
        http_actions = [
            aws.lb.ListenerDefaultActionArgs(
                type="redirect",
                redirect=aws.lb.ListenerDefaultActionRedirectArgs(
                    port="443",
                    protocol="HTTPS",
                    status_code="HTTP_301",
                ),
            )
        ]
    else:
        # HTTP is the main listener and just 404s by default
        http_actions = [
            aws.lb.ListenerDefaultActionArgs(
                type="fixed-response",
                fixed_response=aws.lb.ListenerDefaultActionFixedResponseArgs(
                    content_type="text/plain",
                    message_body="404: Not Found",
                    status_code="404",
                ),
            )
        ]

    listener = aws.lb.Listener(
        f"{name}-http-listener",
        load_balancer_arn=alb.arn,
        port=80,
        protocol="HTTP",
        default_actions=http_actions,
        tags=tags,
    )

    app_listener = listener
    if certificate_arn:
        app_listener = aws.lb.Listener(
            f"{name}-https-listener",
            load_balancer_arn=alb.arn,
            port=443,
            protocol="HTTPS",
            ssl_policy="ELBSecurityPolicy-TLS13-1-2-2021-06",
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

    return AlbResources(
        load_balancer=alb,
        http_listener=listener,
        app_listener=app_listener,
        observability_listener=observability_listener,
    )


def attach_listener_rule(
    *,
    name: str,
    listener_arn: pulumi.Input[str],
    target_group_arn: pulumi.Input[str],
    priority: int,
    path_pattern: pulumi.Input[str] | None = None,
    host_header: pulumi.Input[str] | None = None,
    http_header_name: str | None = None,
    http_header_values: Sequence[pulumi.Input[str]] | None = None,
    tags: dict[str, str] | None = None,
) -> aws.lb.ListenerRule:
    """Attach a forwarding ListenerRule to an existing ALB listener and target group."""
    normalized_name = _require_non_blank(name, field_name="name")
    conditions: list[aws.lb.ListenerRuleConditionArgs] = []
    if path_pattern:
        conditions.append(
            aws.lb.ListenerRuleConditionArgs(
                path_pattern=aws.lb.ListenerRuleConditionPathPatternArgs(
                    values=[path_pattern],
                )
            )
        )
    if host_header:
        conditions.append(
            aws.lb.ListenerRuleConditionArgs(
                host_header=aws.lb.ListenerRuleConditionHostHeaderArgs(
                    values=[host_header],
                )
            )
        )
    if http_header_name and http_header_values:
        conditions.append(
            aws.lb.ListenerRuleConditionArgs(
                http_header=aws.lb.ListenerRuleConditionHttpHeaderArgs(
                    http_header_name=http_header_name,
                    values=http_header_values,
                )
            )
        )

    return aws.lb.ListenerRule(
        normalized_name,
        listener_arn=listener_arn,
        priority=priority,
        actions=[
            aws.lb.ListenerRuleActionArgs(
                type="forward",
                target_group_arn=target_group_arn,
            )
        ],
        conditions=conditions,
        tags=tags,
    )


def provision_target_group_and_rule(
    name: str,
    vpc_id: pulumi.Input[str],
    listener_arn: pulumi.Input[str],
    priority: int,
    path_pattern: pulumi.Input[str] | None = None,
    host_header: pulumi.Input[str] | None = None,
    tags: dict[str, str] | None = None,
    port: int = 8000,
    health_check_path: str = "/health",
    protocol_version: str = "HTTP1",
    http_header_name: str | None = None,
    http_header_values: Sequence[pulumi.Input[str]] | None = None,
    health_check_matcher: str = "200",
    deregistration_delay: int | None = None,
) -> aws.lb.TargetGroup:
    """
    Provisions a Target Group for ECS Fargate and attaches it to the Listener with a path rule.
    """
    tg = aws.lb.TargetGroup(
        f"{name}-tg",
        port=port,
        protocol="HTTP",
        protocol_version=protocol_version,
        vpc_id=vpc_id,
        target_type="ip",
        deregistration_delay=deregistration_delay,
        health_check=aws.lb.TargetGroupHealthCheckArgs(
            path=health_check_path,
            interval=30,
            timeout=5,
            healthy_threshold=2,
            unhealthy_threshold=3,
            matcher=health_check_matcher,
        ),
        tags=tags,
    )

    attach_listener_rule(
        name=f"{name}-rule",
        listener_arn=listener_arn,
        target_group_arn=tg.arn,
        priority=priority,
        path_pattern=path_pattern,
        host_header=host_header,
        http_header_name=http_header_name,
        http_header_values=http_header_values,
        tags=tags,
    )

    return tg


def _require_non_blank(value: str, *, field_name: str) -> str:
    """Validate that a required string input is non-empty after stripping whitespace."""
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string.")
    return normalized


def validate_dns_label(value: str, *, field_name: str = "dns_label") -> str:
    """Validate a single RFC 1123 lowercase DNS label (1-63 chars, alphanumeric and hyphens)."""
    normalized = _require_non_blank(value, field_name=field_name)
    if not _RFC1123_DNS_LABEL_PATTERN.match(normalized):
        raise ValueError(
            f"{field_name} '{normalized}' must be a valid lowercase RFC 1123 DNS label "
            "(1-63 chars, a-z, 0-9, and internal hyphens only)."
        )
    return normalized


def _validate_acm_domain_name(value: str) -> str:
    """Validate a lowercase FQDN or single-level wildcard domain name for AWS ACM."""
    normalized = _require_non_blank(value, field_name="domain_name")
    if len(normalized) > NetworkConstants.MAX_FQDN_LENGTH or not _ACM_DOMAIN_NAME_PATTERN.match(
        normalized
    ):
        raise ValueError(
            f"domain_name '{normalized}' must be a valid lowercase FQDN or single-level wildcard domain."
        )
    return normalized


def _extract_primary_validation_option(
    options: Sequence[aws.acm.outputs.CertificateDomainValidationOption],
) -> aws.acm.outputs.CertificateDomainValidationOption:
    """Return the primary DNS validation option emitted by AWS ACM, failing fast if absent."""
    if not options:
        raise ValueError("ACM certificate returned no domain validation options.")
    return options[0]


def _require_validation_field(value: str | None, *, field_name: str) -> str:
    """Require a populated DNS validation option field returned by AWS ACM."""
    if not value or not value.strip():
        raise ValueError(f"ACM domain validation option is missing required '{field_name}'.")
    return value


def provision_dns_validated_sni_certificate(
    *,
    name: str,
    domain_name: str,
    hosted_zone_id: pulumi.Input[str],
    listener_arn: pulumi.Input[str],
    tags: dict[str, str],
    validation_ttl: int = NetworkConstants.DEFAULT_DNS_VALIDATION_TTL,
) -> SniCertificateResources:
    """Provision a DNS-validated ACM certificate and attach it to an HTTPS ALB listener via SNI.

    This generic primitive is intentionally domain-agnostic: callers supply the exact
    domain name (e.g. a wildcard subdomain), hosted zone ID, and target listener ARN.
    """
    normalized_name = _require_non_blank(name, field_name="name")
    normalized_domain = _validate_acm_domain_name(domain_name)
    if validation_ttl <= 0:
        raise ValueError(f"validation_ttl must be a positive integer, got {validation_ttl}.")

    certificate = aws.acm.Certificate(
        f"{normalized_name}-cert",
        domain_name=normalized_domain,
        validation_method=NetworkConstants.ACM_VALIDATION_METHOD_DNS,
        tags=tags,
        opts=pulumi.ResourceOptions(delete_before_replace=False),
    )

    primary_option = certificate.domain_validation_options.apply(_extract_primary_validation_option)

    validation_record = aws.route53.Record(
        f"{normalized_name}-cert-validation-record",
        zone_id=hosted_zone_id,
        name=primary_option.apply(
            lambda opt: _require_validation_field(
                opt.resource_record_name, field_name="resource_record_name"
            )
        ),
        type=primary_option.apply(
            lambda opt: _require_validation_field(
                opt.resource_record_type, field_name="resource_record_type"
            )
        ),
        records=[
            primary_option.apply(
                lambda opt: _require_validation_field(
                    opt.resource_record_value, field_name="resource_record_value"
                )
            )
        ],
        ttl=validation_ttl,
        allow_overwrite=True,
    )

    certificate_validation = aws.acm.CertificateValidation(
        f"{normalized_name}-cert-validation",
        certificate_arn=certificate.arn,
        validation_record_fqdns=[validation_record.fqdn],
    )

    listener_certificate = aws.lb.ListenerCertificate(
        f"{normalized_name}-listener-cert",
        listener_arn=listener_arn,
        certificate_arn=certificate_validation.certificate_arn,
    )

    return SniCertificateResources(
        certificate=certificate,
        validation=certificate_validation,
        listener_certificate=listener_certificate,
    )


def provision_route53_alias_record(
    *,
    name: str,
    zone_id: pulumi.Input[str],
    record_name: pulumi.Input[str],
    alias_target_dns_name: pulumi.Input[str],
    alias_target_zone_id: pulumi.Input[str],
    evaluate_target_health: bool = False,
) -> aws.route53.Record:
    """Provision a Route53 A Alias record pointing to an AWS edge target (ALB or CloudFront)."""
    normalized_name = _require_non_blank(name, field_name="name")
    return aws.route53.Record(
        normalized_name,
        zone_id=zone_id,
        name=record_name,
        type=NetworkConstants.ROUTE53_RECORD_TYPE_A,
        aliases=[
            aws.route53.RecordAliasArgs(
                name=alias_target_dns_name,
                zone_id=alias_target_zone_id,
                evaluate_target_health=evaluate_target_health,
            )
        ],
    )
