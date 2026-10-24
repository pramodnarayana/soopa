"""Unit tests for declarative manifest loader."""

from __future__ import annotations

import json
from pathlib import Path

from ip.engine.adapters.outbound.connectors.catalog_registry import ConnectorCatalogRegistry
from ip.engine.adapters.outbound.connectors.manifest_loader import (
    load_manifest_from_dict,
    load_manifest_from_file,
    load_manifest_from_json,
    load_manifest_from_yaml,
    load_manifests_from_directory,
)
from ip.engine.domain.exceptions import ConnectorNotFoundError, ManifestParseFailureError
from ip.engine.domain.models.connector_spec import PaginationType, PropertyType


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

    res = load_manifest_from_dict(raw)
    assert res.is_ok is True
    assert res.value is not None
    manifest = res.value
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
    res1 = load_manifest_from_dict({"base_url_template": "https://api.example.com"})
    assert res1.is_err is True
    assert isinstance(res1.error, ManifestParseFailureError)
    assert "missing required 'app_id'" in res1.error.message

    res2 = load_manifest_from_dict({"app_id": "example"})
    assert res2.is_err is True
    assert isinstance(res2.error, ManifestParseFailureError)
    assert "missing required 'base_url_template'" in res2.error.message

    res3 = load_manifest_from_dict(
        {
            "app_id": "example",
            "base_url_template": "https://api.example.com",
            "properties": [{"label": "Invalid"}],
        }
    )
    assert res3.is_err is True
    assert isinstance(res3.error, ManifestParseFailureError)
    assert "missing required 'name' field" in res3.error.message


def test_load_manifest_from_json() -> None:
    valid_json = json.dumps(
        {
            "app_id": "zendesk",
            "base_url_template": "https://{subdomain}.zendesk.com/api/v2",
        }
    )
    res = load_manifest_from_json(valid_json)
    assert res.is_ok is True
    assert res.value is not None
    assert res.value.app_id == "zendesk"

    err1 = load_manifest_from_json("invalid json {[")
    assert err1.is_err is True
    assert isinstance(err1.error, ManifestParseFailureError)
    assert "Invalid JSON" in err1.error.message

    err2 = load_manifest_from_json('["not", "a", "dict"]')
    assert err2.is_err is True
    assert isinstance(err2.error, ManifestParseFailureError)
    assert "must represent a root dictionary" in err2.error.message


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
    res = load_manifest_from_yaml(valid_yaml)
    assert res.is_ok is True
    assert res.value is not None
    manifest = res.value
    assert manifest.app_id == "stripe"
    assert manifest.display_name == "Stripe Payments"
    assert "charges" in manifest.streams

    err1 = load_manifest_from_yaml(":\n invalid yaml %%%")
    assert err1.is_err is True
    assert isinstance(err1.error, ManifestParseFailureError)
    assert "Invalid YAML" in err1.error.message

    err2 = load_manifest_from_yaml("- item1\n- item2")
    assert err2.is_err is True
    assert isinstance(err2.error, ManifestParseFailureError)
    assert "must represent a root dictionary" in err2.error.message


def test_load_manifest_from_file(tmp_path: Path) -> None:
    json_file = tmp_path / "test_connector.json"
    json_file.write_text(
        json.dumps({"app_id": "json_conn", "base_url_template": "https://api.test.com"}),
        encoding="utf-8",
    )
    res = load_manifest_from_file(json_file)
    assert res.is_ok is True
    assert res.value is not None
    assert res.value.app_id == "json_conn"

    yaml_file = tmp_path / "test_connector.yaml"
    yaml_file.write_text(
        "app_id: yaml_conn\nbase_url_template: https://api.test.com\n",
        encoding="utf-8",
    )
    res_yaml = load_manifest_from_file(yaml_file)
    assert res_yaml.is_ok is True
    assert res_yaml.value is not None
    assert res_yaml.value.app_id == "yaml_conn"

    missing_res = load_manifest_from_file(tmp_path / "non_existent.json")
    assert missing_res.is_err is True
    assert isinstance(missing_res.error, ManifestParseFailureError)
    assert "not found" in missing_res.error.message


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
    conn_a_res = registry.get_connector("conn_a")
    assert conn_a_res.is_ok is True
    assert conn_a_res.value is not None
    assert conn_a_res.value.app_id == "conn_a"

    conn_b_res = registry.get_connector("conn_b")
    assert conn_b_res.is_ok is True
    assert conn_b_res.value is not None
    assert conn_b_res.value.app_id == "conn_b"

    corrupted_res = registry.get_connector("corrupted")
    assert corrupted_res.is_err is True
    assert isinstance(corrupted_res.error, ConnectorNotFoundError)

    # Non-existent directory returns 0
    assert load_manifests_from_directory(tmp_path / "does_not_exist", registry) == 0


def test_parse_pagination_preserves_default_param_names() -> None:
    raw = {
        "app_id": "test_app",
        "base_url_template": "https://api.test.com",
        "streams": {
            "items": {
                "path": "/items",
                "pagination": {
                    "pagination_type": "cursor",
                },
            }
        },
    }
    res = load_manifest_from_dict(raw)
    assert res.is_ok is True
    assert res.value is not None
    pag = res.value.streams["items"].pagination
    assert pag.pagination_type == PaginationType.CURSOR
    assert pag.cursor_param == "cursor"
    assert pag.limit_param == "limit"
    assert pag.page_param == "page"
    assert pag.offset_param == "offset"
    assert pag.page_size == 100


def test_parse_pagination_rejects_invalid_page_size() -> None:
    raw: dict[str, object] = {
        "app_id": "test_app",
        "base_url_template": "https://api.test.com",
        "streams": {
            "items": {
                "path": "/items",
                "pagination": {
                    "pagination_type": "offset_limit",
                    "page_size": "not_an_int",
                },
            }
        },
    }
    res1 = load_manifest_from_dict(raw)
    assert res1.is_err is True
    assert isinstance(res1.error, ManifestParseFailureError)
    assert "Invalid page_size" in res1.error.message

    raw_negative: dict[str, object] = {
        "app_id": "test_app",
        "base_url_template": "https://api.test.com",
        "streams": {
            "items": {
                "path": "/items",
                "pagination": {
                    "pagination_type": "offset_limit",
                    "page_size": -10,
                },
            }
        },
    }
    res2 = load_manifest_from_dict(raw_negative)
    assert res2.is_err is True
    assert isinstance(res2.error, ManifestParseFailureError)
    assert "Invalid page_size" in res2.error.message
