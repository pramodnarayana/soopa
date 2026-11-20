import {
  Button,
  cn,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from '@soopa/ui';
import { Check, Copy, Eye, EyeOff, KeyRound, Sparkles } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { toast } from 'sonner';
import type { ConnectorPropertySpec } from '../../domain/catalog';
import { normalizeAuthType } from '../../domain/catalog-auth';
import {
  AuthType,
  ConnectorPropertyKey,
  ConnectorPropertyType,
  type JsonRecord,
} from '../../domain/enums';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';

export interface SplitConnectorFormValues {
  readonly publicConfig: JsonRecord;
  readonly rawCredentials: JsonRecord;
}

const AUTH_PROPERTY_VISIBILITY_RULE: Readonly<Record<string, ReadonlySet<string>>> = {
  [ConnectorPropertyKey.TOKEN]: new Set([AuthType.BEARER_TOKEN, AuthType.API_KEY]),
  [ConnectorPropertyKey.PARAM_NAME]: new Set([AuthType.API_KEY]),
  [ConnectorPropertyKey.PLACEMENT]: new Set([AuthType.API_KEY]),
  [ConnectorPropertyKey.USERNAME]: new Set([
    AuthType.BASIC_AUTH,
    AuthType.SASL_PLAINTEXT,
    AuthType.SASL_SSL,
  ]),
  [ConnectorPropertyKey.PASSWORD]: new Set([
    AuthType.BASIC_AUTH,
    AuthType.SASL_PLAINTEXT,
    AuthType.SASL_SSL,
  ]),
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
  if (prop.name === ConnectorPropertyKey.SECRET_TOKEN || prop.name === 'secret_token') {
    const rawStrat =
      values[ConnectorPropertyKey.VERIFICATION_STRATEGY] ??
      values.verification_strategy ??
      allProperties?.find(
        (p) =>
          p.name === ConnectorPropertyKey.VERIFICATION_STRATEGY ||
          p.name === 'verification_strategy',
      )?.defaultValue;
    if (typeof rawStrat === 'string') {
      const normalizedStrat = rawStrat.trim().toUpperCase();
      if (normalizedStrat === 'PUBLIC_UNAUTHENTICATED' || normalizedStrat === 'NO_AUTH') {
        return false;
      }
    }
  }

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
  if (prop.name === ConnectorPropertyKey.ENDPOINT_SLUG || prop.name === 'endpoint_slug') {
    return 'Webhook URL';
  }
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
  isEditing = false,
}: {
  readonly prop: ConnectorPropertySpec;
  readonly value: string;
  readonly onChange: (val: string) => void;
  readonly currentAuthType?: string | null;
  readonly isEditing?: boolean;
}) {
  const [revealed, setRevealed] = useState(false);
  const normalizedAuth = currentAuthType ? normalizeAuthType(currentAuthType) : null;
  const isSecretToken =
    prop.name === ConnectorPropertyKey.SECRET_TOKEN || prop.name === 'secret_token';

  const handleGenerateSecret = () => {
    const array = new Uint8Array(24);
    if (typeof window !== 'undefined' && window.crypto?.getRandomValues) {
      window.crypto.getRandomValues(array);
    } else {
      for (let i = 0; i < array.length; i++) array[i] = Math.floor(Math.random() * 256);
    }
    const token = Array.from(array, (b) => b.toString(16).padStart(2, '0')).join('');
    onChange(token);
    setRevealed(true);
    toast.success('Generated random secret token.');
  };

  const placeholder =
    prop.type === ConnectorPropertyType.OAUTH
      ? 'Paste OAuth2 refresh/access token or client secret...'
      : prop.name === ConnectorPropertyKey.TOKEN && normalizedAuth === AuthType.BEARER_TOKEN
        ? 'Paste Bearer access token (e.g. eyJhbGci...)...'
        : prop.name === ConnectorPropertyKey.TOKEN && normalizedAuth === AuthType.API_KEY
          ? 'Paste API Key secret value...'
          : prop.name === ConnectorPropertyKey.PASSWORD
            ? 'Enter basic auth password...'
            : isSecretToken
              ? 'Shared secret key or token for verifying signatures...'
              : 'Encrypted AES-256-GCM secret...';

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <Input
          id={`spec-${prop.name}`}
          type={revealed ? 'text' : 'password'}
          value={value}
          required={isEditing ? false : prop.required}
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
        {isSecretToken ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleGenerateSecret}
            className="h-9 gap-1 px-2.5 text-xs font-medium text-foreground hover:bg-accent shrink-0"
            title="Generate secure random secret"
          >
            <Sparkles className="h-3.5 w-3.5 text-indigo-500" />
            <span>Generate</span>
          </Button>
        ) : null}
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

function EndpointSlugPropertyInput({
  prop,
  rawValue,
  onChange,
  tenantSlug,
  baseUrl,
}: {
  readonly prop: ConnectorPropertySpec;
  readonly rawValue: unknown;
  readonly onChange: (nextVal: string) => void;
  readonly tenantSlug?: string;
  readonly baseUrl?: string;
}) {
  let contextTenantSlug = 'tenant';
  let contextBaseUrl = '';
  try {
    const ws = useIpWorkspace();
    contextTenantSlug = ws.tenantSlug || 'tenant';
    contextBaseUrl = ws.baseUrl || '';
  } catch {
    // Graceful fallback when rendered outside IpUIProvider in tests
  }

  const effectiveTenantSlug = (tenantSlug || contextTenantSlug || 'tenant').trim();
  const rawBase = (
    baseUrl ||
    contextBaseUrl ||
    (typeof window !== 'undefined' && window.location?.origin ? window.location.origin : '') ||
    'https://api.soopa.io'
  )
    .trim()
    .replace(/\/+$/, '');
  const prefixUrl = `${rawBase}/api/v1/ingress/${effectiveTenantSlug}/`;

  const slug = coerceScalarString(rawValue ?? prop.defaultValue);
  const fullEndpointUrl = `${prefixUrl}${slug || ''}`;

  const [copied, setCopied] = useState(false);

  const handleSlugChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const rawVal = e.target.value;
    if (rawVal.includes('/api/v1/ingress/')) {
      const parts = rawVal.split('/api/v1/ingress/')[1]?.split('/') || [];
      const extractedSlug = parts.slice(1).join('-') || parts[0] || '';
      onChange(extractedSlug.toLowerCase().replace(/[^a-z0-9_-]/g, '-'));
    } else {
      onChange(rawVal.toLowerCase().replace(/[^a-z0-9_-]/g, '-'));
    }
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(fullEndpointUrl);
      setCopied(true);
      toast.success('Webhook URL copied to clipboard.');
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error('Unable to copy Webhook URL.');
    }
  };

  return (
    <div className="flex items-center rounded-xl border border-input bg-card shadow-xs focus-within:ring-2 focus-within:ring-primary/40 focus-within:border-primary transition-all overflow-hidden w-full">
      <div className="inline-flex select-none items-center border-r border-border bg-muted/60 px-3 py-2 font-mono text-xs text-muted-foreground whitespace-nowrap gap-2">
        <span className="rounded bg-indigo-600/10 dark:bg-indigo-400/20 px-1.5 py-0.5 font-bold text-[10px] text-indigo-700 dark:text-indigo-300">
          POST
        </span>
        <span>{prefixUrl}</span>
      </div>
      <Input
        id={`spec-${prop.name}`}
        type="text"
        value={slug}
        required={prop.required}
        onChange={handleSlugChange}
        placeholder="e.g. oracle-mdm"
        className="border-0 font-mono text-xs rounded-none bg-transparent shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 flex-1 px-3 py-2 font-semibold text-foreground min-w-[120px]"
      />
      <Button
        type="button"
        variant="ghost"
        size="sm"
        disabled={!slug}
        onClick={() => void handleCopy()}
        className="h-8 gap-1.5 px-3 mr-1 text-xs font-medium text-muted-foreground hover:text-foreground shrink-0"
      >
        {copied ? (
          <>
            <Check className="h-3.5 w-3.5 text-emerald-600" />
            <span>Copied</span>
          </>
        ) : (
          <>
            <Copy className="h-3.5 w-3.5" />
            <span>Copy URL</span>
          </>
        )}
      </Button>
    </div>
  );
}

export function SingleSpecPropertyControl({
  prop,
  rawValue,
  onChange,
  currentAuthType,
  isEditing = false,
  tenantSlug,
  baseUrl,
}: {
  readonly prop: ConnectorPropertySpec;
  readonly rawValue: unknown;
  readonly onChange: (nextVal: unknown) => void;
  readonly currentAuthType?: string | null;
  readonly isEditing?: boolean;
  readonly tenantSlug?: string;
  readonly baseUrl?: string;
}) {
  if (prop.name === ConnectorPropertyKey.ENDPOINT_SLUG || prop.name === 'endpoint_slug') {
    return (
      <EndpointSlugPropertyInput
        prop={prop}
        rawValue={rawValue}
        onChange={(val) => onChange(val)}
        tenantSlug={tenantSlug}
        baseUrl={baseUrl}
      />
    );
  }
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
        isEditing={isEditing}
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
  readonly tenantSlug?: string;
  readonly baseUrl?: string;
}

export function SpecFormRenderer({
  properties,
  values,
  onChangeValue,
  tenantSlug,
  baseUrl,
}: SpecFormRendererProps) {
  const rawAuthType =
    values[ConnectorPropertyKey.AUTH_TYPE] ??
    properties.find((p) => p.name === ConnectorPropertyKey.AUTH_TYPE)?.defaultValue;
  const currentAuthType = typeof rawAuthType === 'string' ? normalizeAuthType(rawAuthType) : null;

  const visibleProperties = useMemo(() => {
    const filtered = properties.filter((prop) => isPropertyVisible(prop, values, properties));
    return [...filtered].sort((a, b) => {
      const isEndA = a.name === ConnectorPropertyKey.ENDPOINT_SLUG || a.name === 'endpoint_slug';
      const isEndB = b.name === ConnectorPropertyKey.ENDPOINT_SLUG || b.name === 'endpoint_slug';
      if (isEndA && !isEndB) return 1;
      if (!isEndA && isEndB) return -1;

      const isModA =
        a.name === ConnectorPropertyKey.WEBHOOK_MODALITY || a.name === 'webhook_modality';
      const isModB =
        b.name === ConnectorPropertyKey.WEBHOOK_MODALITY || b.name === 'webhook_modality';
      if (isModA && !isModB) return -1;
      if (!isModA && isModB) return 1;

      return 0;
    });
  }, [properties, values]);

  if (visibleProperties.length === 0) {
    return null;
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {visibleProperties.map((prop) => {
        const displayLabel = resolvePropertyLabel(prop, currentAuthType);
        const isFullWidth =
          prop.type === ConnectorPropertyType.OAUTH ||
          prop.name === 'base_url' ||
          prop.name === 'description' ||
          prop.name === ConnectorPropertyKey.ENDPOINT_SLUG ||
          prop.name === 'endpoint_slug' ||
          visibleProperties.length === 1;

        return (
          <div key={prop.name} className={cn('space-y-1.5', isFullWidth && 'sm:col-span-2')}>
            <Label htmlFor={`spec-${prop.name}`} className="flex items-center gap-1.5">
              <span>{displayLabel}</span>
              {prop.required ? <span className="text-status-critical-fg">*</span> : null}
            </Label>
            <SingleSpecPropertyControl
              prop={prop}
              rawValue={values[prop.name]}
              onChange={(nextVal) => onChangeValue(prop.name, nextVal)}
              currentAuthType={currentAuthType}
              tenantSlug={tenantSlug}
              baseUrl={baseUrl}
            />
          </div>
        );
      })}
    </div>
  );
}
