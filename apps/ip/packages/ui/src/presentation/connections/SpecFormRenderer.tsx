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
import React, { useState } from 'react';
import type { ConnectorPropertySpec } from '../../domain/catalog';
import { ConnectorPropertyType, type JsonRecord } from '../../domain/enums';

export interface SplitConnectorFormValues {
  readonly publicConfig: JsonRecord;
  readonly rawCredentials: JsonRecord;
}

export function isSecretConnectorProperty(prop: ConnectorPropertySpec): boolean {
  return (
    prop.type === ConnectorPropertyType.SECRET_TEXT || prop.type === ConnectorPropertyType.OAUTH
  );
}

export function splitSpecFormValues(
  properties: readonly ConnectorPropertySpec[],
  values: Readonly<Record<string, unknown>>,
): SplitConnectorFormValues {
  const publicConfig: Record<string, unknown> = {};
  const rawCredentials: Record<string, unknown> = {};

  for (const prop of properties) {
    const rawVal = values[prop.name];
    if (rawVal === undefined || rawVal === '') {
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
}: {
  readonly prop: ConnectorPropertySpec;
  readonly value: string;
  readonly onChange: (val: string) => void;
}) {
  const [revealed, setRevealed] = useState(false);
  const placeholder =
    prop.type === ConnectorPropertyType.OAUTH
      ? 'Paste OAuth2 refresh/access token or client secret...'
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
}: {
  readonly prop: ConnectorPropertySpec;
  readonly rawValue: unknown;
  readonly onChange: (nextVal: unknown) => void;
}) {
  if (prop.type === ConnectorPropertyType.BOOLEAN) {
    return <BooleanPropertyInput prop={prop} rawValue={rawValue} onChange={onChange} />;
  }
  if (prop.type === ConnectorPropertyType.DROPDOWN) {
    return <DropdownPropertyInput prop={prop} rawValue={rawValue} onChange={onChange} />;
  }
  if (isSecretConnectorProperty(prop)) {
    return (
      <SecretPropertyInput prop={prop} value={coerceScalarString(rawValue)} onChange={onChange} />
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
  if (properties.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-border p-4 text-xs text-muted-foreground">
        This connector requires no additional configuration properties.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4">
      {properties.map((prop) => (
        <div key={prop.name} className="space-y-1.5">
          <Label htmlFor={`spec-${prop.name}`} className="flex items-center gap-1.5">
            <span>{prop.label}</span>
            {prop.required ? <span className="text-status-critical-fg">*</span> : null}
            <span className="font-mono text-xs font-normal text-muted-foreground">
              ({prop.name})
            </span>
          </Label>
          <SingleSpecPropertyControl
            prop={prop}
            rawValue={values[prop.name]}
            onChange={(nextVal) => onChangeValue(prop.name, nextVal)}
          />
          {prop.description ? (
            <p className="text-xs text-muted-foreground">{prop.description}</p>
          ) : null}
        </div>
      ))}
    </div>
  );
}
