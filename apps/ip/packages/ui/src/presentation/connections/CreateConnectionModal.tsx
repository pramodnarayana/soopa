import {
  ApiErrorCode,
  type ApiProblem,
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Skeleton,
  StatusBadge,
  StatusTone,
} from '@soopa/ui';
import { CheckCircle2, PlugZap } from 'lucide-react';
import React, { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { useCatalogAppSpecQuery, useCatalogAppsQuery } from '../../application/use-catalog-queries';
import {
  useCheckConnectionMutation,
  useCreateConnectionMutation,
} from '../../application/use-connection-queries';
import type { AppSpec, CatalogAppSummary } from '../../domain/catalog';
import { normalizeAuthType } from '../../domain/catalog-auth';
import type { ConnectionCheckResult } from '../../domain/connection';
import { ConnectorPropertyKey } from '../../domain/enums';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { buildFailedCheckProblem, isConnectionSnapshotVerified } from './connection-preflight';
import { isPropertyVisible, SpecFormRenderer, splitSpecFormValues } from './SpecFormRenderer';

export interface CreateConnectionModalProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly onCreated: (connectionId: string) => void;
  readonly initialApp?: CatalogAppSummary | null;
}

function MarketplaceStep({
  onSelectApp,
  onCancel,
}: {
  readonly onSelectApp: (app: CatalogAppSummary) => void;
  readonly onCancel: () => void;
}) {
  const [search, setSearch] = useState('');
  const appsView = useCatalogAppsQuery({ search: search.trim() || undefined });
  const apps = appsView.data ?? [];

  return (
    <>
      <ApiProblemBanner problem={appsView.problem} />
      <div className="space-y-4">
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search connectors by name or category (e.g. Itron, SAP, Salesforce, S3)..."
        />

        {appsView.isLoading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Skeleton className="h-24 w-full rounded-xl" />
            <Skeleton className="h-24 w-full rounded-xl" />
          </div>
        ) : (
          <div className="grid max-h-96 grid-cols-1 gap-3 overflow-y-auto pr-1 sm:grid-cols-2">
            {apps.map((app) => (
              <Button
                key={app.appId}
                type="button"
                variant="outline"
                onClick={() => onSelectApp(app)}
                className="h-auto flex-col items-start gap-1.5 rounded-xl p-4 text-left hover:border-primary hover:bg-accent/60"
              >
                <div className="flex w-full items-center justify-between gap-2">
                  <span className="font-semibold text-foreground">{app.displayName}</span>
                  <StatusBadge label={app.authType} tone={StatusTone.NEUTRAL} />
                </div>
                <span className="font-mono text-xs text-brand-ink">
                  {app.category} · {app.runtimeArchitecture}
                </span>
                {app.description ? (
                  <p className="line-clamp-2 text-xs text-muted-foreground whitespace-normal">
                    {app.description}
                  </p>
                ) : null}
              </Button>
            ))}
          </div>
        )}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
      </DialogFooter>
    </>
  );
}

function VerifiedSpecConfigurator({
  spec,
  defaultName,
  onCreated,
}: {
  readonly spec: AppSpec;
  readonly defaultName: string;
  readonly onCreated: (connectionId: string) => void;
}) {
  const [connectionName, setConnectionName] = useState(defaultName);
  const [formValues, setFormValues] = useState<Record<string, unknown>>({});
  const [verifiedSnapshot, setVerifiedSnapshot] = useState<string | null>(null);
  const [checkResult, setCheckResult] = useState<ConnectionCheckResult | null>(null);
  const [problem, setProblem] = useState<ApiProblem | null>(null);

  const checkMutation = useCheckConnectionMutation();
  const createMutation = useCreateConnectionMutation();

  const currentSnapshot = useMemo(() => JSON.stringify(formValues), [formValues]);
  const isVerified = isConnectionSnapshotVerified(currentSnapshot, verifiedSnapshot, checkResult);

  const hasRequiredFields = useMemo(() => {
    if (connectionName.trim().length === 0) return false;
    for (const prop of spec.properties) {
      if (!prop.required) continue;
      if (!isPropertyVisible(prop, formValues, spec.properties)) continue;
      const val = formValues[prop.name] ?? prop.defaultValue;
      if (val === undefined || val === null || String(val).trim().length === 0) {
        return false;
      }
    }
    return true;
  }, [connectionName, spec.properties, formValues]);

  const canSave = hasRequiredFields && !createMutation.isPending;

  const resolveEffectiveAuthType = (): string => {
    const defaultAuthFromProps = spec.properties.find(
      (p) => p.name === ConnectorPropertyKey.AUTH_TYPE,
    )?.defaultValue;
    const raw =
      (formValues[ConnectorPropertyKey.AUTH_TYPE] as string | undefined) ??
      (typeof defaultAuthFromProps === 'string' ? defaultAuthFromProps : spec.authType);
    return raw;
  };

  const handleRunPreflight = async (): Promise<void> => {
    setProblem(null);
    const effectiveAuth = resolveEffectiveAuthType();
    const normalizedAuth = normalizeAuthType(effectiveAuth);
    if (!normalizedAuth) {
      setProblem({
        code: ApiErrorCode.VALIDATION_ERROR,
        status: 400,
        serverCode: 'UNSUPPORTED_AUTH_TYPE',
        message: `Connector auth type "${effectiveAuth}" is not recognized or supported.`,
      });
      return;
    }
    const { publicConfig, rawCredentials } = splitSpecFormValues(spec.properties, formValues);
    const res = await checkMutation.mutateAsync({
      appId: spec.appId,
      authType: normalizedAuth,
      publicConfig,
      rawCredentials,
    });
    if (!res.ok) {
      setProblem(res.error);
      return;
    }
    if (!res.value.success) {
      setProblem(buildFailedCheckProblem(res.value));
      return;
    }
    setCheckResult(res.value);
    setVerifiedSnapshot(currentSnapshot);
  };

  const handleSave = async (): Promise<void> => {
    setProblem(null);
    const effectiveAuth = resolveEffectiveAuthType();
    const normalizedAuth = normalizeAuthType(effectiveAuth);
    if (!normalizedAuth) {
      setProblem({
        code: ApiErrorCode.VALIDATION_ERROR,
        status: 400,
        serverCode: 'UNSUPPORTED_AUTH_TYPE',
        message: `Connector auth type "${effectiveAuth}" is not recognized or supported.`,
      });
      return;
    }
    const { publicConfig, rawCredentials } = splitSpecFormValues(spec.properties, formValues);
    const res = await createMutation.mutateAsync({
      appId: spec.appId,
      name: connectionName.trim(),
      authType: normalizedAuth,
      publicConfig,
      rawCredentials,
    });
    if (!res.ok) {
      setProblem(res.error);
      return;
    }
    toast.success(`Encrypted connection "${res.value.name}" created.`);
    onCreated(res.value.id);
  };

  return (
    <>
      <ApiProblemBanner problem={problem} />
      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="new-connection-name">Connection Name *</Label>
          <Input
            id="new-connection-name"
            value={connectionName}
            onChange={(e) => setConnectionName(e.target.value)}
            placeholder={`Production ${spec.displayName}`}
          />
        </div>

        <SpecFormRenderer
          properties={spec.properties}
          values={formValues}
          onChangeValue={(name, val) => setFormValues((prev) => ({ ...prev, [name]: val }))}
        />

        {isVerified && checkResult ? (
          <div className="flex items-center gap-2 rounded-xl border border-status-healthy-border bg-status-healthy-bg px-3.5 py-2.5 text-xs text-status-healthy-fg">
            <CheckCircle2 className="h-4 w-4 shrink-0" />
            <span>
              Pre-Flight Passed ({checkResult.status}):{' '}
              {checkResult.message ?? 'Connector credentials verified.'}
            </span>
          </div>
        ) : null}
      </div>

      <DialogFooter className="gap-2">
        <Button
          type="button"
          variant="outline"
          disabled={checkMutation.isPending}
          onClick={() => void handleRunPreflight()}
          className="gap-1.5"
        >
          <PlugZap className="h-4 w-4" />
          <span>{checkMutation.isPending ? 'Testing...' : 'Test Connection'}</span>
        </Button>
        <Button
          type="button"
          disabled={!canSave}
          onClick={() => void handleSave()}
          className="gap-1.5"
        >
          <span>{createMutation.isPending ? 'Saving...' : 'Save'}</span>
        </Button>
      </DialogFooter>
    </>
  );
}

export function CreateConnectionModal({
  open,
  onOpenChange,
  onCreated,
  initialApp,
}: CreateConnectionModalProps) {
  const [selectedApp, setSelectedApp] = useState<CatalogAppSummary | null>(initialApp ?? null);

  useEffect(() => {
    if (open) {
      setSelectedApp(initialApp ?? null);
    }
  }, [open, initialApp]);

  const specView = useCatalogAppSpecQuery(selectedApp?.appId ?? null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {selectedApp ? `Connect ${selectedApp.displayName}` : 'Catalog'}
          </DialogTitle>
        </DialogHeader>

        {!selectedApp ? (
          <MarketplaceStep onSelectApp={setSelectedApp} onCancel={() => onOpenChange(false)} />
        ) : specView.isLoading || !specView.data ? (
          <>
            <ApiProblemBanner problem={specView.problem} />
            <Skeleton className="h-56 w-full rounded-xl" />
          </>
        ) : (
          <VerifiedSpecConfigurator
            key={selectedApp.appId}
            spec={specView.data}
            defaultName={`${selectedApp.displayName} Primary`}
            onCreated={(id) => {
              onOpenChange(false);
              onCreated(id);
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
