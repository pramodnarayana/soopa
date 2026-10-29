import type { AppSpec, CatalogAppSummary, ConnectorPropertySpec } from '../../../domain/catalog';
import type {
  AppSpecWire,
  CatalogAppSummaryWire,
  ConnectorPropertyWire,
} from '../schemas/catalog.schema';

export function mapCatalogAppSummaryFromWire(wire: CatalogAppSummaryWire): CatalogAppSummary {
  return {
    appId: wire.app_id,
    displayName: wire.display_name,
    category: wire.category,
    authType: wire.auth_type,
    description: wire.description,
    connectorType: wire.connector_type,
    iconUrl: wire.icon_url,
  };
}

export function mapConnectorPropertyFromWire(wire: ConnectorPropertyWire): ConnectorPropertySpec {
  return {
    name: wire.name,
    label: wire.label,
    type: wire.type,
    required: wire.required,
    defaultValue: wire.default,
    description: wire.description,
    options: wire.options.map((opt) => ({
      label: opt.label,
      value: opt.value,
    })),
    oauthConfig: wire.oauth_config
      ? {
          authUrl: wire.oauth_config.auth_url,
          tokenUrl: wire.oauth_config.token_url,
          scopes: wire.oauth_config.scopes,
          clientId: wire.oauth_config.client_id,
        }
      : null,
  };
}

export function mapAppSpecFromWire(wire: AppSpecWire): AppSpec {
  return {
    appId: wire.app_id,
    displayName: wire.display_name,
    authType: wire.auth_type,
    category: wire.category,
    properties: wire.properties.map(mapConnectorPropertyFromWire),
    description: wire.description,
  };
}
