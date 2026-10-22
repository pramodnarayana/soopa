"""Declarative Manifest Loader for parsing Airbyte/Activepieces-style JSON/YAML connector specifications."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import structlog
import yaml
from ip.engine.adapters.outbound.connectors.catalog_registry import ConnectorCatalogRegistry
from ip.engine.domain.exceptions import ManifestParseFailureError, Result
from ip.engine.domain.models.connector_spec import (
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


def _parse_property(
    raw_prop: Mapping[str, object],
) -> Result[ConnectorProperty, ManifestParseFailureError]:
    name = raw_prop.get("name")
    if not name:
        return Result.fail(
            ManifestParseFailureError(
                field_name="name",
                message="Connector property is missing required 'name' field",
                details={"field": "name"},
            )
        )

    label = raw_prop.get("label", name)
    raw_type = str(raw_prop.get("type", "shortText"))
    try:
        prop_type = PropertyType(raw_type)
    except ValueError:
        prop_type = PropertyType.SHORT_TEXT

    options: list[DropdownOption] = []
    raw_options = raw_prop.get("options")
    if isinstance(raw_options, (list, tuple)):
        for opt in raw_options:
            if isinstance(opt, dict) and "label" in opt and "value" in opt:
                options.append(DropdownOption(label=str(opt["label"]), value=str(opt["value"])))

    oauth_config = None
    raw_oauth = raw_prop.get("oauth_config")
    if isinstance(raw_oauth, dict):
        oauth_scopes = raw_oauth.get("scopes")
        scopes = (
            tuple(str(s) for s in oauth_scopes)
            if isinstance(oauth_scopes, (list, tuple))
            else ()
        )
        oauth_config = OAuthConfig(
            auth_url=str(raw_oauth.get("auth_url", "")),
            token_url=str(raw_oauth.get("token_url", "")),
            scopes=scopes,
            client_id=str(raw_oauth["client_id"]) if "client_id" in raw_oauth else None,
        )

    raw_default = raw_prop.get("default")
    default_val: str | int | float | bool | None = (
        raw_default if isinstance(raw_default, (str, int, float, bool)) else None
    )

    return Result.ok(
        ConnectorProperty(
            name=str(name),
            label=str(label),
            type=prop_type,
            required=bool(raw_prop.get("required", True)),
            default=default_val,
            description=str(raw_prop["description"]) if raw_prop.get("description") else None,
            options=tuple(options),
            oauth_config=oauth_config,
        )
    )


def _parse_pagination(
    raw_pag: Mapping[str, object] | None,
) -> Result[PaginationConfig, ManifestParseFailureError]:
    if not raw_pag:
        return Result.ok(PaginationConfig())

    raw_pag_type = str(raw_pag.get("pagination_type", "none")).lower()
    try:
        pag_type = PaginationType(raw_pag_type)
    except ValueError:
        pag_type = PaginationType.NONE

    cursor_param = (
        str(raw_pag["cursor_param"])
        if "cursor_param" in raw_pag and raw_pag["cursor_param"] is not None
        else "cursor"
    )
    cursor_path = (
        str(raw_pag["cursor_path"])
        if "cursor_path" in raw_pag and raw_pag["cursor_path"] is not None
        else None
    )
    limit_param = (
        str(raw_pag["limit_param"])
        if "limit_param" in raw_pag and raw_pag["limit_param"] is not None
        else "limit"
    )
    page_param = (
        str(raw_pag["page_param"])
        if "page_param" in raw_pag and raw_pag["page_param"] is not None
        else "page"
    )
    offset_param = (
        str(raw_pag["offset_param"])
        if "offset_param" in raw_pag and raw_pag["offset_param"] is not None
        else "offset"
    )

    raw_page_size = raw_pag.get("page_size", 100)
    if not isinstance(raw_page_size, (int, str)):
        return Result.fail(
            ManifestParseFailureError(
                field_name="page_size",
                message=f"Invalid page_size in pagination config: {raw_page_size}",
                details={"page_size": str(raw_page_size)},
            )
        )
    try:
        page_size = int(raw_page_size)
    except ValueError:
        return Result.fail(
            ManifestParseFailureError(
                field_name="page_size",
                message=f"Invalid page_size in pagination config: {raw_page_size}",
                details={"page_size": str(raw_page_size)},
            )
        )
    if page_size <= 0:
        return Result.fail(
            ManifestParseFailureError(
                field_name="page_size",
                message=f"Invalid page_size in pagination config: {raw_page_size}",
                details={"page_size": page_size},
            )
        )

    return Result.ok(
        PaginationConfig(
            pagination_type=pag_type,
            cursor_param=cursor_param,
            cursor_path=cursor_path,
            limit_param=limit_param,
            page_param=page_param,
            offset_param=offset_param,
            page_size=page_size,
        )
    )


def _parse_http_method(raw_method: str) -> Literal["GET", "POST", "PUT", "PATCH", "DELETE"]:
    upper = raw_method.upper()
    if upper == "POST":
        return "POST"
    if upper == "PUT":
        return "PUT"
    if upper == "PATCH":
        return "PATCH"
    if upper == "DELETE":
        return "DELETE"
    return "GET"


def _parse_action_spec(
    raw_action: Mapping[str, object],
) -> Result[HttpActionSpec, ManifestParseFailureError]:
    path = raw_action.get("path", "/")
    method = _parse_http_method(str(raw_action.get("method", "GET")))
    raw_headers = raw_action.get("headers")
    headers = (
        {str(k): str(v) for k, v in raw_headers.items()}
        if isinstance(raw_headers, dict)
        else {}
    )
    raw_params = raw_action.get("query_params")
    query_params = (
        {str(k): str(v) for k, v in raw_params.items()}
        if isinstance(raw_params, dict)
        else {}
    )
    raw_pagination = raw_action.get("pagination")
    pag_res = _parse_pagination(
        raw_pagination if isinstance(raw_pagination, dict) else None
    )
    if pag_res.error is not None or pag_res.value is None:
        return Result.fail(
            pag_res.error
            or ManifestParseFailureError(message="Invalid pagination configuration")
        )
    records_path = raw_action.get("response_records_path")

    return Result.ok(
        HttpActionSpec(
            path=str(path),
            method=method,
            headers=headers,
            query_params=query_params,
            pagination=pag_res.value,
            response_records_path=str(records_path) if records_path else None,
        )
    )


def _parse_properties_list(
    raw_props: Sequence[object] | object,
) -> Result[list[ConnectorProperty], ManifestParseFailureError]:
    if not isinstance(raw_props, (list, tuple)):
        return Result.ok([])
    parsed: list[ConnectorProperty] = []
    for p in raw_props:
        if isinstance(p, dict):
            prop_res = _parse_property(p)
            if prop_res.error is not None or prop_res.value is None:
                return Result.fail(
                    prop_res.error
                    or ManifestParseFailureError(message="Invalid connector property")
                )
            parsed.append(prop_res.value)
    return Result.ok(parsed)


def _parse_action_map(
    raw_map: Mapping[str, object] | object,
) -> Result[dict[str, HttpActionSpec], ManifestParseFailureError]:
    if not isinstance(raw_map, dict):
        return Result.ok({})
    parsed: dict[str, HttpActionSpec] = {}
    for k, v in raw_map.items():
        if isinstance(v, dict):
            act_res = _parse_action_spec(v)
            if act_res.error is not None or act_res.value is None:
                return Result.fail(
                    act_res.error
                    or ManifestParseFailureError(message="Invalid HTTP action specification")
                )
            parsed[str(k)] = act_res.value
    return Result.ok(parsed)


def load_manifest_from_dict(
    raw: Mapping[str, object],
) -> Result[DeclarativeManifest, ManifestParseFailureError]:
    """Parses a dictionary representation into a strongly-typed DeclarativeManifest Result."""
    app_id = raw.get("app_id")
    if not app_id:
        return Result.fail(
            ManifestParseFailureError(
                field_name="app_id",
                message="Manifest is missing required 'app_id' field",
                details={"field": "app_id"},
            )
        )

    base_url_template = raw.get("base_url_template")
    if not base_url_template:
        return Result.fail(
            ManifestParseFailureError(
                field_name="base_url_template",
                message="Manifest is missing required 'base_url_template' field",
                details={"field": "base_url_template"},
            )
        )

    display_name = raw.get("display_name", app_id)
    category = str(raw.get("category", "MISC")).upper()
    auth_type = str(raw.get("auth_type", "API_KEY")).upper()

    props_res = _parse_properties_list(raw.get("properties"))
    if props_res.error is not None or props_res.value is None:
        return Result.fail(
            props_res.error or ManifestParseFailureError(message="Invalid properties list")
        )

    prop_schema = ConnectorPropertySchema(
        app_id=str(app_id),
        display_name=str(display_name),
        auth_type=auth_type,
        category=category,
        properties=tuple(props_res.value),
        description=str(raw["description"]) if raw.get("description") else None,
    )

    raw_check = raw.get("check")
    check_action: HttpActionSpec | None = None
    if isinstance(raw_check, dict):
        check_res = _parse_action_spec(raw_check)
        if check_res.error is not None or check_res.value is None:
            return Result.fail(
                check_res.error or ManifestParseFailureError(message="Invalid check action")
            )
        check_action = check_res.value

    streams_res = _parse_action_map(raw.get("streams"))
    if streams_res.error is not None or streams_res.value is None:
        return Result.fail(
            streams_res.error or ManifestParseFailureError(message="Invalid streams map")
        )

    write_res = _parse_action_map(raw.get("write_actions"))
    if write_res.error is not None or write_res.value is None:
        return Result.fail(
            write_res.error or ManifestParseFailureError(message="Invalid write_actions map")
        )

    return Result.ok(
        DeclarativeManifest(
            app_id=str(app_id),
            display_name=str(display_name),
            category=category,
            auth_type=auth_type,
            base_url_template=str(base_url_template),
            property_schema=prop_schema,
            check_action=check_action,
            streams=streams_res.value,
            write_actions=write_res.value,
        )
    )


def load_manifest_from_json(
    json_str: str,
) -> Result[DeclarativeManifest, ManifestParseFailureError]:
    """Parses a JSON string into a DeclarativeManifest Result."""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        return Result.fail(
            ManifestParseFailureError(
                message=f"Invalid JSON in declarative manifest: {exc}",
            )
        )

    if not isinstance(data, dict):
        return Result.fail(
            ManifestParseFailureError(
                message="Manifest JSON must represent a root dictionary/object",
            )
        )
    return load_manifest_from_dict(data)


def load_manifest_from_yaml(
    yaml_str: str,
) -> Result[DeclarativeManifest, ManifestParseFailureError]:
    """Parses a YAML string into a DeclarativeManifest Result."""
    try:
        data = yaml.safe_load(yaml_str)
    except yaml.YAMLError as exc:
        return Result.fail(
            ManifestParseFailureError(
                message=f"Invalid YAML in declarative manifest: {exc}",
            )
        )

    if not isinstance(data, dict):
        return Result.fail(
            ManifestParseFailureError(
                message="Manifest YAML must represent a root dictionary/object",
            )
        )
    return load_manifest_from_dict(data)


def load_manifest_from_file(
    file_path: Path | str,
) -> Result[DeclarativeManifest, ManifestParseFailureError]:
    """Reads a .json or .yaml manifest file from disk into a Result."""
    path = Path(file_path)
    if not path.is_file():
        return Result.fail(
            ManifestParseFailureError(
                field_name="file_path",
                message=f"Manifest file not found: {path}",
                details={"file_path": str(path)},
            )
        )

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return Result.fail(
            ManifestParseFailureError(
                field_name="file_path",
                message=f"Unable to read manifest file {path}: {exc}",
                details={"file_path": str(path)},
            )
        )

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
            manifest_res = load_manifest_from_file(file)
            if manifest_res.is_ok and manifest_res.value is not None:
                registry.register_manifest(manifest_res.value)
                registered_count += 1
            else:
                err_msg = (
                    manifest_res.error.message
                    if manifest_res.error is not None
                    else "Unknown manifest parse error"
                )
                logger.error(
                    "manifest_file_parse_skipped",
                    file_path=str(file),
                    error=err_msg,
                )

    return registered_count
