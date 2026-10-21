"""Declarative Manifest Loader for parsing Airbyte/Activepieces-style JSON/YAML connector specifications."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
import yaml
from ip.adapters.outbound.connectors.catalog_registry import ConnectorCatalogRegistry
from ip.domain.exceptions import IpDomainException
from ip.domain.models.connector_spec import (
    ConnectorProperty,
    ConnectorPropertySchema,
    DeclarativeManifest,
    DropdownOption,
    HttpActionSpec,
    OAuthConfig,
    PaginationConfig,
    PaginationType,
    PropertyType,
)

logger = structlog.get_logger(__name__)


class ManifestParseError(IpDomainException):
    """Raised when a declarative manifest cannot be validated or parsed."""


def _parse_property(raw_prop: dict[str, Any]) -> ConnectorProperty:
    name = raw_prop.get("name")
    if not name:
        raise ManifestParseError("Connector property is missing required 'name' field")

    label = raw_prop.get("label", name)
    raw_type = str(raw_prop.get("type", "shortText"))
    try:
        prop_type = PropertyType(raw_type)
    except ValueError:
        prop_type = PropertyType.SHORT_TEXT

    options: list[DropdownOption] = []
    if "options" in raw_prop and isinstance(raw_prop["options"], list):
        for opt in raw_prop["options"]:
            if isinstance(opt, dict) and "label" in opt and "value" in opt:
                options.append(DropdownOption(label=str(opt["label"]), value=str(opt["value"])))

    oauth_config = None
    if "oauth_config" in raw_prop and isinstance(raw_prop["oauth_config"], dict):
        oauth_dict = raw_prop["oauth_config"]
        oauth_config = OAuthConfig(
            auth_url=str(oauth_dict.get("auth_url", "")),
            token_url=str(oauth_dict.get("token_url", "")),
            scopes=tuple(str(s) for s in oauth_dict.get("scopes", ())),
            client_id=str(oauth_dict["client_id"]) if "client_id" in oauth_dict else None,
        )

    return ConnectorProperty(
        name=str(name),
        label=str(label),
        type=prop_type,
        required=bool(raw_prop.get("required", True)),
        default=raw_prop.get("default"),
        description=str(raw_prop["description"]) if raw_prop.get("description") else None,
        options=tuple(options),
        oauth_config=oauth_config,
    )


def _parse_pagination(raw_pag: dict[str, Any] | None) -> PaginationConfig:
    if not raw_pag:
        return PaginationConfig()

    raw_pag_type = str(raw_pag.get("pagination_type", "none")).lower()
    try:
        pag_type = PaginationType(raw_pag_type)
    except ValueError:
        pag_type = PaginationType.NONE

    return PaginationConfig(
        pagination_type=pag_type,
        cursor_param=raw_pag.get("cursor_param"),
        cursor_path=raw_pag.get("cursor_path"),
        limit_param=raw_pag.get("limit_param"),
        page_param=raw_pag.get("page_param"),
        offset_param=raw_pag.get("offset_param"),
        page_size=int(raw_pag.get("page_size", 100)),
    )


def _parse_action_spec(raw_action: dict[str, Any]) -> HttpActionSpec:
    path = raw_action.get("path", "/")
    method = str(raw_action.get("method", "GET")).upper()
    headers = {str(k): str(v) for k, v in raw_action.get("headers", {}).items()}
    query_params = {str(k): str(v) for k, v in raw_action.get("query_params", {}).items()}
    pagination = _parse_pagination(raw_action.get("pagination"))
    records_path = raw_action.get("response_records_path")

    return HttpActionSpec(
        path=str(path),
        method=method,
        headers=headers,
        query_params=query_params,
        pagination=pagination,
        response_records_path=str(records_path) if records_path else None,
    )


def _parse_properties_list(raw_props: Any) -> list[ConnectorProperty]:
    if not isinstance(raw_props, list):
        return []
    return [_parse_property(p) for p in raw_props if isinstance(p, dict)]


def _parse_action_map(raw_map: Any) -> dict[str, HttpActionSpec]:
    if not isinstance(raw_map, dict):
        return {}
    return {str(k): _parse_action_spec(v) for k, v in raw_map.items() if isinstance(v, dict)}


def load_manifest_from_dict(raw: dict[str, Any]) -> DeclarativeManifest:
    """Parses a dictionary representation into a strongly-typed DeclarativeManifest."""
    app_id = raw.get("app_id")
    if not app_id:
        raise ManifestParseError("Manifest is missing required 'app_id' field")

    base_url_template = raw.get("base_url_template")
    if not base_url_template:
        raise ManifestParseError("Manifest is missing required 'base_url_template' field")

    display_name = raw.get("display_name", app_id)
    category = str(raw.get("category", "MISC")).upper()
    auth_type = str(raw.get("auth_type", "API_KEY")).upper()

    prop_schema = ConnectorPropertySchema(
        app_id=str(app_id),
        display_name=str(display_name),
        auth_type=auth_type,
        category=category,
        properties=tuple(_parse_properties_list(raw.get("properties"))),
        description=str(raw["description"]) if raw.get("description") else None,
    )

    check_action = _parse_action_spec(raw["check"]) if isinstance(raw.get("check"), dict) else None
    streams = _parse_action_map(raw.get("streams"))
    write_actions = _parse_action_map(raw.get("write_actions"))

    return DeclarativeManifest(
        app_id=str(app_id),
        display_name=str(display_name),
        category=category,
        auth_type=auth_type,
        base_url_template=str(base_url_template),
        property_schema=prop_schema,
        check_action=check_action,
        streams=streams,
        write_actions=write_actions,
    )


def load_manifest_from_json(json_str: str) -> DeclarativeManifest:
    """Parses a JSON string into a DeclarativeManifest."""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ManifestParseError(f"Invalid JSON in declarative manifest: {exc}") from exc

    if not isinstance(data, dict):
        raise ManifestParseError("Manifest JSON must represent a root dictionary/object")
    return load_manifest_from_dict(data)


def load_manifest_from_yaml(yaml_str: str) -> DeclarativeManifest:
    """Parses a YAML string into a DeclarativeManifest."""
    try:
        data = yaml.safe_load(yaml_str)
    except yaml.YAMLError as exc:
        raise ManifestParseError(f"Invalid YAML in declarative manifest: {exc}") from exc

    if not isinstance(data, dict):
        raise ManifestParseError("Manifest YAML must represent a root dictionary/object")
    return load_manifest_from_dict(data)


def load_manifest_from_file(file_path: Path | str) -> DeclarativeManifest:
    """Reads a .json or .yaml manifest file from disk."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Manifest file not found: {path}")

    content = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        return load_manifest_from_yaml(content)
    return load_manifest_from_json(content)


def load_manifests_from_directory(
    dir_path: Path | str,
    registry: ConnectorCatalogRegistry,
) -> int:
    """Discovers and registers all .json and .yaml manifests from a directory into the catalog registry."""
    path = Path(dir_path)
    if not path.is_dir():
        return 0

    registered_count = 0
    for file in sorted(path.iterdir()):
        if file.suffix.lower() in (".json", ".yaml", ".yml"):
            try:
                manifest = load_manifest_from_file(file)
                registry.register_manifest(manifest)
                registered_count += 1
            except ManifestParseError as exc:
                logger.error(
                    "manifest_file_parse_skipped",
                    file_path=str(file),
                    error=str(exc),
                )
                continue

    return registered_count
