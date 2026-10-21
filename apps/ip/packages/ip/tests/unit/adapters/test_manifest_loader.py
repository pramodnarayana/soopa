"""Unit tests for declarative manifest loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ip.adapters.outbound.connectors.catalog_registry import ConnectorCatalogRegistry
from ip.adapters.outbound.connectors.manifest_loader import (
    ManifestParseError,
    load_manifest_from_dict,
    load_manifest_from_file,
    load_manifest_from_json,
    load_manifest_from_yaml,
    load_manifests_from_directory,
)
from ip.domain.exceptions import ConnectorNotFoundException
from ip.domain.models.connector_spec import PaginationType, PropertyType


def test_load_manifest_from_dict_success() -> None:
    raw = {
        "app_id": "hubspot_crm",
        "display_name": "HubSpot CRM",
        "category": "CRM",
        "auth_type": "OAUTH2",
        "base_url_template": "https://api.hubapi.com/crm/v3",
        "description": "HubSpot CRM integration",
        "properties": [
            {
                "name": "access_token",
                "label": "Access Token",
                "type": "oauth2",
                "required": True,
                "oauth_config": {
                    "auth_url": "https://app.hubspot.com/oauth/authorize",
                    "token_url": "https://api.hubapi.com/oauth/v1/token",
                    "scopes": ["crm.objects.contacts.read"],
                },
            },
            {
                "name": "region",
                "label": "Region",
                "type": "dropdown",
                "required": False,
                "options": [
                    {"label": "US", "value": "us"},
                    {"label": "EU", "value": "eu"},
                ],
            },
        ],
        "check": {
            "path": "/objects/contacts",
            "method": "GET",
            "query_params": {"limit": "1"},
        },
        "streams": {
            "contacts": {
                "path": "/objects/contacts",
                "method": "GET",
                "response_records_path": "results",
                "pagination": {
                    "pagination_type": "CURSOR",
                    "cursor_param": "after",
                    "cursor_path": "paging.next.after",
                    "page_size": 100,
                },
            }
        },
        "write_actions": {
            "contacts": {
                "path": "/objects/contacts",
                "method": "POST",
            }
        },
    }

    manifest = load_manifest_from_dict(raw)
    assert manifest.app_id == "hubspot_crm"
    assert manifest.display_name == "HubSpot CRM"
    assert manifest.category == "CRM"
    assert manifest.auth_type == "OAUTH2"
    assert manifest.base_url_template == "https://api.hubapi.com/crm/v3"

    assert len(manifest.property_schema.properties) == 2
    token_prop = manifest.property_schema.properties[0]
    assert token_prop.name == "access_token"
    assert token_prop.type == PropertyType.OAUTH2
    assert token_prop.oauth_config is not None
    assert token_prop.oauth_config.scopes == ("crm.objects.contacts.read",)

    region_prop = manifest.property_schema.properties[1]
    assert region_prop.type == PropertyType.DROPDOWN
    assert len(region_prop.options) == 2
    assert region_prop.options[0].value == "us"

    assert manifest.check_action is not None
    assert manifest.check_action.path == "/objects/contacts"
    assert "contacts" in manifest.streams
    assert manifest.streams["contacts"].pagination.pagination_type == PaginationType.CURSOR
    assert manifest.streams["contacts"].response_records_path == "results"
    assert "contacts" in manifest.write_actions


def test_load_manifest_from_dict_missing_required_fields() -> None:
    with pytest.raises(ManifestParseError, match="missing required 'app_id'"):
        load_manifest_from_dict({"base_url_template": "https://api.example.com"})

    with pytest.raises(ManifestParseError, match="missing required 'base_url_template'"):
        load_manifest_from_dict({"app_id": "example"})

    with pytest.raises(ManifestParseError, match="missing required 'name' field"):
        load_manifest_from_dict(
            {
                "app_id": "example",
                "base_url_template": "https://api.example.com",
                "properties": [{"label": "Invalid"}],
            }
        )


def test_load_manifest_from_json() -> None:
    valid_json = json.dumps(
        {
            "app_id": "zendesk",
            "base_url_template": "https://{subdomain}.zendesk.com/api/v2",
        }
    )
    manifest = load_manifest_from_json(valid_json)
    assert manifest.app_id == "zendesk"

    with pytest.raises(ManifestParseError, match="Invalid JSON"):
        load_manifest_from_json("invalid json {[")

    with pytest.raises(ManifestParseError, match="must represent a root dictionary"):
        load_manifest_from_json('["not", "a", "dict"]')


def test_load_manifest_from_yaml() -> None:
    valid_yaml = """
app_id: stripe
display_name: Stripe Payments
auth_type: BEARER
base_url_template: https://api.stripe.com/v1
streams:
  charges:
    path: /charges
    method: GET
"""
    manifest = load_manifest_from_yaml(valid_yaml)
    assert manifest.app_id == "stripe"
    assert manifest.display_name == "Stripe Payments"
    assert "charges" in manifest.streams

    with pytest.raises(ManifestParseError, match="Invalid YAML"):
        load_manifest_from_yaml(":\n invalid yaml %%%")

    with pytest.raises(ManifestParseError, match="must represent a root dictionary"):
        load_manifest_from_yaml("- item1\n- item2")


def test_load_manifest_from_file(tmp_path: Path) -> None:
    json_file = tmp_path / "test_connector.json"
    json_file.write_text(
        json.dumps({"app_id": "json_conn", "base_url_template": "https://api.test.com"}),
        encoding="utf-8",
    )
    manifest = load_manifest_from_file(json_file)
    assert manifest.app_id == "json_conn"

    yaml_file = tmp_path / "test_connector.yaml"
    yaml_file.write_text(
        "app_id: yaml_conn\nbase_url_template: https://api.test.com\n",
        encoding="utf-8",
    )
    manifest_yaml = load_manifest_from_file(yaml_file)
    assert manifest_yaml.app_id == "yaml_conn"

    with pytest.raises(FileNotFoundError):
        load_manifest_from_file(tmp_path / "non_existent.json")


def test_load_manifests_from_directory(tmp_path: Path) -> None:
    registry = ConnectorCatalogRegistry()

    # Create 2 valid manifests, 1 invalid manifest, and 1 non-manifest file
    (tmp_path / "connector_a.json").write_text(
        json.dumps({"app_id": "conn_a", "base_url_template": "https://a.com"}),
        encoding="utf-8",
    )
    (tmp_path / "connector_b.yaml").write_text(
        "app_id: conn_b\nbase_url_template: https://b.com\n",
        encoding="utf-8",
    )
    (tmp_path / "corrupted.json").write_text("not json", encoding="utf-8")
    (tmp_path / "readme.txt").write_text("documentation", encoding="utf-8")

    count = load_manifests_from_directory(tmp_path, registry)
    assert count == 2
    assert registry.get_connector("conn_a").app_id == "conn_a"
    assert registry.get_connector("conn_b").app_id == "conn_b"
    with pytest.raises(ConnectorNotFoundException):
        registry.get_connector("corrupted")

    # Non-existent directory returns 0
    assert load_manifests_from_directory(tmp_path / "does_not_exist", registry) == 0
