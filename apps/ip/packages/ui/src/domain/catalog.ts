import type {
  AuthTypeValue,
  ConnectorPropertyTypeValue,
  ConnectorRuntimeArchitectureValue,
} from './enums';

export interface DropdownOption {
  readonly label: string;
  readonly value: string;
}

export interface OAuthConfig {
  readonly authUrl: string;
  readonly tokenUrl: string;
  readonly scopes: readonly string[];
  readonly clientId: string | null;
}

export interface ConnectorPropertySpec {
  readonly name: string;
  readonly label: string;
  readonly type: ConnectorPropertyTypeValue;
  readonly required: boolean;
  readonly defaultValue: string | number | boolean | null;
  readonly description: string | null;
  readonly options: readonly DropdownOption[];
  readonly oauthConfig: OAuthConfig | null;
}

export interface CatalogAppSummary {
  readonly appId: string;
  readonly displayName: string;
  readonly category: string;
  readonly authType: AuthTypeValue | (string & {});
  readonly description: string | null;
  readonly runtimeArchitecture: ConnectorRuntimeArchitectureValue;
  readonly iconUrl: string | null;
}

export interface AppSpec {
  readonly appId: string;
  readonly displayName: string;
  readonly authType: AuthTypeValue | (string & {});
  readonly category: string;
  readonly properties: readonly ConnectorPropertySpec[];
  readonly description: string | null;
}

export interface CatalogAppsFilter {
  readonly category?: string;
  readonly search?: string;
}
