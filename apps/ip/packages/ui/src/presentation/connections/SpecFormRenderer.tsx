import {
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from '@soopa/ui';
import { Eye, EyeOff, KeyRound } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import type { ConnectorPropertySpec } from '../../domain/catalog';
import { normalizeAuthType } from '../../domain/catalog-auth';
import {
  AuthType,
  ConnectorPropertyKey,
  ConnectorPropertyType,
  type JsonRecord,
} from '../../domain/enums';

export interface SplitConnectorFormValues {
  readonly publicConfig: JsonRecord;
  readonly rawCredentials: JsonRecord;
}

const AUTH_PROPERTY_VISIBILITY_RULE: Readonly<Record<string, ReadonlySet<string>>> = {
  [ConnectorPropertyKey.TOKEN]: new Set([AuthType.BEARER_TOKEN, AuthType.API_KEY]),
  [ConnectorPropertyKey.PARAM_NAME]: new Set([AuthType.API_KEY]),
  [ConnectorPropertyKey.PLACEMENT]: new Set([AuthType.API_KEY]),
  [ConnectorPropertyKey.USERNAME]: new Set([AuthType.BASIC_AUTH]),
  [ConnectorPropertyKey.PASSWORD]: new Set([AuthType.BASIC_AUTH]),
  [ConnectorPropertyKey.TOKEN_URL]: new Set([AuthType.OAUTH2_CLIENT_CREDENTIALS, AuthType.OAUTH2]),
  [ConnectorPropertyKey.CLIENT_ID]: new Set([AuthType.OAUTH2_CLIENT_CREDENTIALS, AuthType.OAUTH2]),
  [ConnectorPropertyKey.CLIENT_SECRET]: new Set([
    AuthType.OAUTH2_CLIENT_CREDENTIALS,
    AuthType.OAUTH2,
  ]),
};

export function isSecretConnectorProperty(prop: ConnectorPropertySpec): boolean {
  return (
    prop.type === ConnectorPropertyType.SECRET_TEXT || prop.type === ConnectorPropertyType.OAUTH
  );
}

export function isPropertyVisible(
  prop: ConnectorPropertySpec,
  values: Readonly<Record<string, unknown>>,
  allProperties?: readonly ConnectorPropertySpec[],
): boolean {
  const hasAuthTypeProp =
    allProperties?.some((p) => p.name === ConnectorPropertyKey.AUTH_TYPE) ?? false;
  const rawAuthType =
    values[ConnectorPropertyKey.AUTH_TYPE] ??
    allProperties?.find((p) => p.name === ConnectorPropertyKey.AUTH_TYPE)?.defaultValue;
  const currentAuthType = typeof rawAuthType === 'string' ? normalizeAuthType(rawAuthType) : null;

  // Only apply dynamic auth-based filtering if an auth_type discriminator exists
  if (!hasAuthTypeProp && values[ConnectorPropertyKey.AUTH_TYPE] === undefined) {
    return true;
  }

  if (!currentAuthType) {
    return true;
  }

  const allowedAuthTypes = AUTH_PROPERTY_VISIBILITY_RULE[prop.name];
  if (allowedAuthTypes) {
    return allowedAuthTypes.has(currentAuthType);
  }

  return true;
}

export function resolvePropertyLabel(
  prop: ConnectorPropertySpec,
  currentAuthType?: string | null,
): string {
  if (prop.name === ConnectorPropertyKey.TOKEN && currentAuthType) {
    const normalized = normalizeAuthType(currentAuthType);
    if (normalized === AuthType.BEARER_TOKEN) {
      return 'Bearer Token';
    }
    if (normalized === AuthType.API_KEY) {
      return 'API Key Secret';
    }
  }
  return prop.label;
}

export function resolvePropertyDescription(
  prop: ConnectorPropertySpec,
  currentAuthType?: string | null,
): string | null {
  if (prop.name === ConnectorPropertyKey.TOKEN && currentAuthType) {
    const normalized = normalizeAuthType(currentAuthType);
    if (normalized === AuthType.BEARER_TOKEN) {
      return 'Bearer token sent in the Authorization header (Authorization: Bearer <token>).';
    }
    if (normalized === AuthType.API_KEY) {
      return 'API key secret passed via header or query parameter.';
    }
  }
  return prop.description;
}

export function splitSpecFormValues(
  properties: readonly ConnectorPropertySpec[],
  values: Readonly<Record<string, unknown>>,
): SplitConnectorFormValues {
  const publicConfig: Record<string, unknown> = {};
  const rawCredentials: Record<string, unknown> = {};

  for (const prop of properties) {
    if (!isPropertyVisible(prop, values, properties)) {
      continue;
    }
    const rawVal = values[prop.name] !== undefined ? values[prop.name] : prop.defaultValue;
    if (rawVal === undefined || rawVal === null || rawVal === '') {
      continue;
    }
    if (isSecretConnectorProperty(prop)) {
      rawCredentials[prop.name] = rawVal;
    } else {
      publicConfig[prop.name] = rawVal;
    }
  }

  return { publicConfig, rawCredentials };
}

function coerceScalarString(value: unknown): string {
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return '';
}

function SecretPropertyInput({
  prop,
  value,
  onChange,
  currentAuthType,
}: {
  readonly prop: ConnectorPropertySpec;
  readonly value: string;
  readonly onChange: (val: string) => void;
  readonly currentAuthType?: string | null;
}) {
  const [revealed, setRevealed] = useState(false);
  const normalizedAuth = currentAuthType ? normalizeAuthType(currentAuthType) : null;
  const placeholder =
    prop.type === ConnectorPropertyType.OAUTH
      ? 'Paste OAuth2 refresh/access token or client secret...'
      : prop.name === ConnectorPropertyKey.TOKEN && normalizedAuth === AuthType.BEARER_TOKEN
        ? 'Paste Bearer access token (e.g. eyJhbGci...)...'
        : prop.name === ConnectorPropertyKey.TOKEN && normalizedAuth === AuthType.API_KEY
          ? 'Paste API Key secret value...'
          : prop.name === ConnectorPropertyKey.PASSWORD
            ? 'Enter basic auth password...'
            : 'Encrypted AES-256-GCM secret...';

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <Input
          id={`spec-${prop.name}`}
          type={revealed ? 'text' : 'password'}
          value={value}
          required={prop.required}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="font-mono text-xs"
        />
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={() => setRevealed((prev) => !prev)}
          aria-label={revealed ? `Hide ${prop.label}` : `Reveal ${prop.label}`}
        >
          {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </Button>
      </div>
      {prop.oauthConfig ? (
        <div className="flex items-center gap-1.5 rounded-lg border border-border bg-accent/40 px-2.5 py-1.5 text-xs text-muted-foreground">
          <KeyRound className="h-3.5 w-3.5 text-brand-ink" />
          <span>
            OAuth2 Token Endpoint: <span className="font-mono">{prop.oauthConfig.tokenUrl}</span>{' '}
            (Scopes: {prop.oauthConfig.scopes.join(', ') || 'default'})
          </span>
        </div>
      ) : null}
    </div>
  );
}

function BooleanPropertyInput({
  prop,
  rawValue,
  onChange,
}: {
  readonly prop: ConnectorPropertySpec;
  readonly rawValue: unknown;
  readonly onChange: (nextVal: boolean) => void;
}) {
  const checked = typeof rawValue === 'boolean' ? rawValue : Boolean(prop.defaultValue);
  return (
    <div className="flex items-center gap-2.5 pt-1">
      <Switch id={`spec-${prop.name}`} checked={checked} onCheckedChange={onChange} />
      <span className="text-xs text-muted-foreground">{checked ? 'Enabled' : 'Disabled'}</span>
    </div>
  );
}

function DropdownPropertyInput({
  prop,
  rawValue,
  onChange,
}: {
  readonly prop: ConnectorPropertySpec;
  readonly rawValue: unknown;
  readonly onChange: (nextVal: string) => void;
}) {
  const selected = coerceScalarString(rawValue ?? prop.defaultValue);
  return (
    <Select value={selected} onValueChange={onChange}>
      <SelectTrigger id={`spec-${prop.name}`} aria-label={prop.label}>
        <SelectValue placeholder={`Select ${prop.label}`} />
      </SelectTrigger>
      <SelectContent>
        {prop.options.map((opt) => (
          <SelectItem key={opt.value} value={opt.value}>
            {opt.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function NumberPropertyInput({
  prop,
  rawValue,
  onChange,
}: {
  readonly prop: ConnectorPropertySpec;
  readonly rawValue: unknown;
  readonly onChange: (nextVal: number | '') => void;
}) {
  const numStr = coerceScalarString(rawValue ?? prop.defaultValue);
  return (
    <Input
      id={`spec-${prop.name}`}
      type="number"
      value={numStr}
      required={prop.required}
      onChange={(e) => {
        const parsed = Number(e.target.value);
        onChange(e.target.value === '' || Number.isNaN(parsed) ? '' : parsed);
      }}
    />
  );
}

function SingleSpecPropertyControl({
  prop,
  rawValue,
  onChange,
  currentAuthType,
}: {
  readonly prop: ConnectorPropertySpec;
  readonly rawValue: unknown;
  readonly onChange: (nextVal: unknown) => void;
  readonly currentAuthType?: string | null;
}) {
  if (prop.type === ConnectorPropertyType.BOOLEAN) {
    return <BooleanPropertyInput prop={prop} rawValue={rawValue} onChange={onChange} />;
  }
  if (prop.type === ConnectorPropertyType.DROPDOWN) {
    return <DropdownPropertyInput prop={prop} rawValue={rawValue} onChange={onChange} />;
  }
  if (isSecretConnectorProperty(prop)) {
    return (
      <SecretPropertyInput
        prop={prop}
        value={coerceScalarString(rawValue)}
        onChange={onChange}
        currentAuthType={currentAuthType}
      />
    );
  }
  if (prop.type === ConnectorPropertyType.NUMBER) {
    return <NumberPropertyInput prop={prop} rawValue={rawValue} onChange={onChange} />;
  }
  return (
    <Input
      id={`spec-${prop.name}`}
      type="text"
      value={coerceScalarString(rawValue ?? prop.defaultValue)}
      required={prop.required}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export interface SpecFormRendererProps {
  readonly properties: readonly ConnectorPropertySpec[];
  readonly values: Readonly<Record<string, unknown>>;
  readonly onChangeValue: (name: string, nextVal: unknown) => void;
}

export function SpecFormRenderer({ properties, values, onChangeValue }: SpecFormRendererProps) {
  const rawAuthType =
    values[ConnectorPropertyKey.AUTH_TYPE] ??
    properties.find((p) => p.name === ConnectorPropertyKey.AUTH_TYPE)?.defaultValue;
  const currentAuthType = typeof rawAuthType === 'string' ? normalizeAuthType(rawAuthType) : null;

  const visibleProperties = useMemo(
    () => properties.filter((prop) => isPropertyVisible(prop, values, properties)),
    [properties, values],
  );

  if (visibleProperties.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-border p-4 text-xs text-muted-foreground">
        This connector requires no additional configuration properties.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4">
      {visibleProperties.map((prop) => {
        const displayLabel = resolvePropertyLabel(prop, currentAuthType);
        const displayDescription = resolvePropertyDescription(prop, currentAuthType);
        return (
          <div key={prop.name} className="space-y-1.5">
            <Label htmlFor={`spec-${prop.name}`} className="flex items-center gap-1.5">
              <span>{displayLabel}</span>
              {prop.required ? <span className="text-status-critical-fg">*</span> : null}
              <span className="font-mono text-xs font-normal text-muted-foreground">
                ({prop.name})
              </span>
            </Label>
            <SingleSpecPropertyControl
              prop={prop}
              rawValue={values[prop.name]}
              onChange={(nextVal) => onChangeValue(prop.name, nextVal)}
              currentAuthType={currentAuthType}
            />
            {displayDescription ? (
              <p className="text-xs text-muted-foreground">{displayDescription}</p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
