"""Unit and architectural contract tests for wildcard SNI TLS certificates and AS2 edge routing."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from pathlib import Path

import pulumi
import pytest
from infra_seedwork.constants import NetworkConstants
from infra_seedwork.network import (
    AlbResources,
    SniCertificateResources,
    _extract_primary_validation_option,
    _require_validation_field,
    attach_listener_rule,
    provision_alb,
    provision_dns_validated_sni_certificate,
    provision_route53_alias_record,
    validate_dns_label,
)
from pulumi.runtime import MockCallArgs, MockResourceArgs, Mocks, set_mocks
from pulumi.runtime.settings import SETTINGS
from pulumi.runtime.stack import run_pulumi_func

AWS_ROOT = Path(__file__).resolve().parents[1]
SEEDWORK_NETWORK_PATH = AWS_ROOT / "packages" / "seedwork" / "infra_seedwork" / "network.py"


def _run_pulumi_test(fn: Callable[[], pulumi.Output[None]]) -> None:
    async def _runner() -> None:
        SETTINGS.rpc_manager.clear()
        SETTINGS.outputs.clear()
        await run_pulumi_func(lambda: fn().future())

    asyncio.run(_runner())


class _NetworkTlsMocks(Mocks):
    def __init__(self) -> None:
        self.created_resources: list[tuple[str, str, dict[str, object]]] = []

    def new_resource(self, args: MockResourceArgs) -> tuple[str | None, dict[str, object]]:
        inputs = dict(args.inputs)
        self.created_resources.append((args.typ, args.name, inputs))

        if args.typ == "aws:acm/certificate:Certificate":
            domain = str(inputs.get("domainName", "*.as2.staging.flowwolf.io"))
            arn = f"arn:aws:acm:us-east-1:634680389104:certificate/{args.name}"
            return f"{args.name}-id", {
                **inputs,
                "arn": arn,
                "domainValidationOptions": [
                    {
                        "domainName": domain,
                        "resourceRecordName": "_abc123.as2.staging.flowwolf.io.",
                        "resourceRecordType": "CNAME",
                        "resourceRecordValue": "_xyz789.acm-validations.aws.",
                    }
                ],
            }
        if args.typ == "aws:route53/record:Record":
            record_name = str(inputs.get("name", ""))
            return f"{args.name}-id", {
                **inputs,
                "fqdn": record_name.rstrip("."),
            }
        if args.typ == "aws:acm/certificateValidation:CertificateValidation":
            return f"{args.name}-id", {
                **inputs,
                "certificateArn": inputs.get("certificateArn", ""),
            }
        if args.typ == "aws:lb/loadBalancer:LoadBalancer":
            return f"{args.name}-id", {
                **inputs,
                "arn": f"arn:aws:elasticloadbalancing:us-east-1:634680389104:loadbalancer/app/{args.name}/123",
            }
        if args.typ == "aws:lb/listener:Listener":
            return f"{args.name}-id", {
                **inputs,
                "arn": f"arn:aws:elasticloadbalancing:us-east-1:634680389104:listener/app/main/{args.name}",
            }
        return f"{args.name}-id", inputs

    def call(self, args: MockCallArgs) -> tuple[dict[str, object], list[tuple[str, str]]]:
        return ({}, [])


def test_provision_dns_validated_sni_certificate_wires_acm_sni_stack() -> None:
    """Verify generic SNI certificate primitive creates ACM cert, DNS CNAME, validation, and ALB SNI attachment."""
    mocks = _NetworkTlsMocks()

    def _verify() -> pulumi.Output[None]:
        set_mocks(mocks, project="platform", stack="staging", preview=False)
        bundle = provision_dns_validated_sni_certificate(
            name="staging-wildcard-sni",
            domain_name="*.as2.staging.flowwolf.io",
            hosted_zone_id="Z1234567890",
            listener_arn="arn:aws:elasticloadbalancing:us-east-1:634680389104:listener/app/main/abc/def",
            tags={"Environment": "staging"},
        )
        assert isinstance(bundle, SniCertificateResources)

        def _assert(values: list[str]) -> None:
            cert_arn, validated_arn, attached_arn = values[0], values[1], values[2]
            assert (
                cert_arn
                == "arn:aws:acm:us-east-1:634680389104:certificate/staging-wildcard-sni-cert"
            )
            assert validated_arn == cert_arn
            assert attached_arn == cert_arn

            resource_types = [typ for typ, _, _ in mocks.created_resources]
            assert resource_types == [
                "aws:acm/certificate:Certificate",
                "aws:route53/record:Record",
                "aws:acm/certificateValidation:CertificateValidation",
                "aws:lb/listenerCertificate:ListenerCertificate",
            ]

            _, _, cert_inputs = mocks.created_resources[0]
            assert cert_inputs["domainName"] == "*.as2.staging.flowwolf.io"
            assert cert_inputs["validationMethod"] == NetworkConstants.ACM_VALIDATION_METHOD_DNS

            _, _, r53_inputs = mocks.created_resources[1]
            assert r53_inputs["zoneId"] == "Z1234567890"
            assert r53_inputs["name"] == "_abc123.as2.staging.flowwolf.io."
            assert r53_inputs["type"] == "CNAME"
            assert r53_inputs["records"] == ["_xyz789.acm-validations.aws."]
            assert r53_inputs["allowOverwrite"] is True

            _, _, val_inputs = mocks.created_resources[2]
            assert val_inputs["validationRecordFqdns"] == ["_abc123.as2.staging.flowwolf.io"]

            _, _, sni_inputs = mocks.created_resources[3]
            assert (
                sni_inputs["listenerArn"]
                == "arn:aws:elasticloadbalancing:us-east-1:634680389104:listener/app/main/abc/def"
            )
            assert sni_inputs["certificateArn"] == cert_arn

        return pulumi.Output.all(
            bundle.certificate.arn,
            bundle.certificate_arn,
            bundle.listener_certificate.certificate_arn,
        ).apply(_assert)

    _run_pulumi_test(_verify)


@pytest.mark.parametrize(
    ("name", "domain_name", "validation_ttl"),
    [
        ("", "*.as2.staging.flowwolf.io", 60),
        ("   ", "*.as2.staging.flowwolf.io", 60),
        ("staging-wildcard", "", 60),
        ("staging-wildcard", "   ", 60),
        ("staging-wildcard", "not a domain", 60),
        ("staging-wildcard", "UPPER.staging.flowwolf.io", 60),
        ("staging-wildcard", "*.*.as2.staging.flowwolf.io", 60),
        ("staging-wildcard", "localhost", 60),
        ("staging-wildcard", "*.as2.staging.flowwolf.io", 0),
        ("staging-wildcard", "*.as2.staging.flowwolf.io", -10),
    ],
)
def test_provision_dns_validated_sni_certificate_rejects_invalid_inputs(
    name: str, domain_name: str, validation_ttl: int
) -> None:
    """Fail fast on blank names, malformed domains, or non-positive validation TTLs."""
    with pytest.raises(ValueError):
        provision_dns_validated_sni_certificate(
            name=name,
            domain_name=domain_name,
            hosted_zone_id="Z1234567890",
            listener_arn="arn:aws:elasticloadbalancing:us-east-1:634680389104:listener/app/main/abc/def",
            tags={"Environment": "staging"},
            validation_ttl=validation_ttl,
        )


def test_extract_primary_validation_option_rejects_empty_sequence() -> None:
    """Fail fast when AWS ACM returns zero domain validation options."""
    with pytest.raises(ValueError, match="no domain validation options"):
        _extract_primary_validation_option([])


@pytest.mark.parametrize("missing_value", [None, "", "   "])
def test_require_validation_field_rejects_blank_values(missing_value: str | None) -> None:
    """Fail fast when an ACM validation option field is absent or blank."""
    with pytest.raises(ValueError, match="resource_record_name"):
        _require_validation_field(missing_value, field_name="resource_record_name")


@pytest.mark.parametrize("valid_label", ["a", "greatlakes", "staging-test", "tenant-123"])
def test_validate_dns_label_accepts_valid_rfc1123_labels(valid_label: str) -> None:
    """Accept valid lowercase RFC 1123 DNS labels."""
    assert validate_dns_label(f" {valid_label} ", field_name="test_tenant_slug") == valid_label


@pytest.mark.parametrize(
    "invalid_label",
    ["", "   ", "GREAT_LAKES", "bad_slug", "-leading", "trailing-", "has.dot", "a" * 64],
)
def test_validate_dns_label_rejects_invalid_rfc1123_labels(invalid_label: str) -> None:
    """Reject blank, uppercase, underscored, dotted, or oversized DNS labels."""
    with pytest.raises(ValueError):
        validate_dns_label(invalid_label, field_name="test_tenant_slug")


def test_provision_route53_alias_record_creates_a_alias_record() -> None:
    """Verify reusable Route53 alias primitive provisions a typed A Alias record."""
    mocks = _NetworkTlsMocks()

    def _verify() -> pulumi.Output[None]:
        set_mocks(mocks, project="routing", stack="staging", preview=False)
        record = provision_route53_alias_record(
            name="staging-as2-wildcard-dns",
            zone_id="Z1234567890",
            record_name="*.as2.staging.flowwolf.io",
            alias_target_dns_name="main-alb-123.us-east-1.elb.amazonaws.com",
            alias_target_zone_id="Z35SXDOTRQ7X7K",
        )

        def _assert(record_name: str) -> None:
            assert record_name == "*.as2.staging.flowwolf.io"
            assert len(mocks.created_resources) == 1
            typ, res_name, inputs = mocks.created_resources[0]
            assert typ == "aws:route53/record:Record"
            assert res_name == "staging-as2-wildcard-dns"
            assert inputs["zoneId"] == "Z1234567890"
            assert inputs["type"] == NetworkConstants.ROUTE53_RECORD_TYPE_A
            aliases = inputs["aliases"]
            assert isinstance(aliases, list)
            assert len(aliases) == 1
            assert aliases[0]["name"] == "main-alb-123.us-east-1.elb.amazonaws.com"
            assert aliases[0]["zoneId"] == "Z35SXDOTRQ7X7K"
            assert aliases[0]["evaluateTargetHealth"] is False

        output: pulumi.Output[None] = record.name.apply(_assert)
        return output

    _run_pulumi_test(_verify)


def test_provision_route53_alias_record_rejects_blank_name() -> None:
    """Fail fast when Route53 alias resource name is empty."""
    with pytest.raises(ValueError):
        provision_route53_alias_record(
            name="  ",
            zone_id="Z1234567890",
            record_name="*.as2.staging.flowwolf.io",
            alias_target_dns_name="main-alb-123.us-east-1.elb.amazonaws.com",
            alias_target_zone_id="Z35SXDOTRQ7X7K",
        )


def test_infra_seedwork_network_contains_zero_bounded_context_leakage() -> None:
    """Enforce Pure & Independent Seedwork: zero domain names inside infra_seedwork/network.py."""
    source = SEEDWORK_NETWORK_PATH.read_text(encoding="utf-8").lower()
    for forbidden in ("flowwolf", "as2", "edi", "ucp", "identity", "notification"):
        assert re.search(rf"\b{re.escape(forbidden)}\b", source) is None, (
            f"Seedwork network module must remain domain-agnostic; found '{forbidden}'."
        )


def test_platform_stack_provisions_as2_wildcard_sni_certificate() -> None:
    """Verify platform stack provisions *.as2.<domain> SNI certificate via typed bundle."""
    platform_source = (AWS_ROOT / "platform" / "__main__.py").read_text(encoding="utf-8")
    assert "as2_sni_cert = provision_dns_validated_sni_certificate(" in platform_source
    assert 'as2_base_domain = f"as2.{staging_domain}"' in platform_source
    assert 'as2_wildcard_domain = f"*.{as2_base_domain}"' in platform_source


def test_platform_stack_exports_as2_wildcard_outputs() -> None:
    """Verify platform stack exports as2_base_domain, as2_wildcard_domain, and as2_wildcard_cert_arn."""
    platform_source = (AWS_ROOT / "platform" / "__main__.py").read_text(encoding="utf-8")
    assert 'pulumi.export("as2_base_domain", as2_base_domain)' in platform_source
    assert 'pulumi.export("as2_wildcard_domain", as2_wildcard_domain)' in platform_source
    assert 'pulumi.export("as2_wildcard_cert_arn", as2_sni_cert.certificate_arn)' in platform_source


def test_platform_stack_exports_http_listener_arn_for_legacy_http_as2_partners() -> None:
    """Verify platform stack exports main_alb_http_listener_arn so AS2 can accept both HTTP and HTTPS."""
    platform_source = (AWS_ROOT / "platform" / "__main__.py").read_text(encoding="utf-8")
    assert 'pulumi.export("main_alb_http_listener_arn", main_http_listener.arn)' in platform_source


def test_provision_alb_exposes_distinct_http_https_listeners() -> None:
    """Verify provision_alb returns AlbResources exposing both port 80 HTTP and port 443 HTTPS listeners."""
    mocks = _NetworkTlsMocks()

    def _verify() -> pulumi.Output[None]:
        set_mocks(mocks, project="platform", stack="staging", preview=False)
        resources = provision_alb(
            name="staging-main",
            subnets=["subnet-a", "subnet-b"],
            security_group_id="sg-123",
            tags={"Environment": "staging"},
            certificate_arn="arn:aws:acm:us-east-1:634680389104:certificate/main",
        )
        assert isinstance(resources, AlbResources)

        def _assert(arns: list[str]) -> None:
            http_arn, https_arn, obs_arn = arns[0], arns[1], arns[2]
            assert http_arn.endswith("/staging-main-http-listener")
            assert https_arn.endswith("/staging-main-https-listener")
            assert obs_arn.endswith("/staging-main-obs-listener")
            assert http_arn != https_arn

        return pulumi.Output.all(
            resources.http_listener.arn,
            resources.app_listener.arn,
            resources.observability_listener.arn,
        ).apply(_assert)

    _run_pulumi_test(_verify)


def test_attach_listener_rule_forwards_matching_traffic_directly() -> None:
    """Verify attach_listener_rule attaches a direct forward rule for dual HTTP/HTTPS listeners."""
    mocks = _NetworkTlsMocks()

    def _verify() -> pulumi.Output[None]:
        set_mocks(mocks, project="edi-as2", stack="staging", preview=False)
        rule = attach_listener_rule(
            name="staging-edi-as2-http-rule",
            listener_arn="arn:aws:elasticloadbalancing:us-east-1:634680389104:listener/app/main/http",
            target_group_arn="arn:aws:elasticloadbalancing:us-east-1:634680389104:targetgroup/as2/123",
            priority=404,
            host_header="*.as2.staging.flowwolf.io",
            path_pattern="/inbox",
            tags={"Environment": "staging"},
        )

        def _assert(priority: int) -> None:
            assert priority == 404
            assert len(mocks.created_resources) == 1
            typ, res_name, inputs = mocks.created_resources[0]
            assert typ == "aws:lb/listenerRule:ListenerRule"
            assert res_name == "staging-edi-as2-http-rule"
            actions = inputs["actions"]
            assert isinstance(actions, list)
            assert actions[0]["type"] == "forward"

        output: pulumi.Output[None] = rule.priority.apply(_assert)
        return output

    _run_pulumi_test(_verify)


def test_routing_stack_provisions_wildcard_as2_alias() -> None:
    """Verify routing stack provisions *.as2.<domain> alias record via reusable primitive."""
    routing_source = (AWS_ROOT / "apps" / "routing" / "__main__.py").read_text(encoding="utf-8")
    assert "provision_route53_alias_record" in routing_source
    assert '"*.as2."' in routing_source
    assert 'pulumi.export("as2_wildcard_domain", as2_wildcard_dns_record.name)' in routing_source


def test_routing_stack_retires_legacy_edi_subdomain() -> None:
    """Verify routing stack contains zero legacy edi.<domain> records or exports."""
    routing_source = (AWS_ROOT / "apps" / "routing" / "__main__.py").read_text(encoding="utf-8")
    assert '"edi."' not in routing_source
    assert "edi_dns_record" not in routing_source
    assert '"edi_domain"' not in routing_source


def test_openas2_stack_targets_v1_per_tenant_as2_inbox_url() -> None:
    """Verify OpenAS2 staging simulator strictly validates slug and targets V1 per-tenant /inbox URL."""
    openas2_source = (AWS_ROOT / "apps" / "openas2" / "__main__.py").read_text(encoding="utf-8")
    assert "validate_dns_label(" in openas2_source
    assert "raw_test_tenant_slug is None" in openas2_source
    assert '".as2.", staging_domain, "/inbox"' in openas2_source
    assert "https://edi." not in openas2_source
