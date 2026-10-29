import {
  type ApiProblem,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Skeleton,
  StatusBadge,
  StatusTone,
} from '@soopa/ui';
import { CheckCircle2, PlugZap, ShieldCheck } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { toast } from 'sonner';
import { useCatalogAppSpecQuery, useCatalogAppsQuery } from '../../application/use-catalog-queries';
import {
  useCheckConnectionMutation,
  useCreateConnectionMutation,
} from '../../application/use-connection-queries';
import type { AppSpec, CatalogAppSummary } from '../../domain/catalog';
import { normalizeAuthType } from '../../domain/catalog-auth';
import type { ConnectionCheckResult } from '../../domain/connection';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { buildFailedCheckProblem, isConnectionSnapshotVerified } from './connection-preflight';
import { SpecFormRenderer, splitSpecFormValues } from './SpecFormRenderer';

export interface CreateConnectionModalProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly onCreated: (connectionId: string) => void;
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
                  {app.category} · {app.connectorType}
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
  onBack,
  onCreated,
}: {
  readonly spec: AppSpec;
  readonly defaultName: string;
  readonly onBack: () => void;
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
  const canSave = isVerified && connectionName.trim().length > 0 && !createMutation.isPending;

  const handleRunPreflight = async (): Promise<void> => {
    setProblem(null);
    const { publicConfig, rawCredentials } = splitSpecFormValues(spec.properties, formValues);
    const res = await checkMutation.mutateAsync({
      appId: spec.appId,
      authType: normalizeAuthType(spec.authType),
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
    const { publicConfig, rawCredentials } = splitSpecFormValues(spec.properties, formValues);
    const res = await createMutation.mutateAsync({
      appId: spec.appId,
      name: connectionName.trim(),
      authType: normalizeAuthType(spec.authType),
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
      <div className="max-h-96 space-y-4 overflow-y-auto pr-1">
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
        <Button type="button" variant="ghost" onClick={onBack}>
          Back to Catalog
        </Button>
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
          <ShieldCheck className="h-4 w-4" />
          <span>{createMutation.isPending ? 'Encrypting...' : 'Save Encrypted Connection'}</span>
        </Button>
      </DialogFooter>
    </>
  );
}

export function CreateConnectionModal({
  open,
  onOpenChange,
  onCreated,
}: CreateConnectionModalProps) {
  const [selectedApp, setSelectedApp] = useState<CatalogAppSummary | null>(null);
  const specView = useCatalogAppSpecQuery(selectedApp?.appId ?? null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {selectedApp
              ? `Configure ${selectedApp.displayName} Connection`
              : 'New Connector From Catalog'}
          </DialogTitle>
          <DialogDescription>
            {selectedApp
              ? 'Run a live pre-flight connection check before persisting AES-256-GCM encrypted credentials.'
              : 'Select a verified enterprise connector specification from the Integration Platform catalog.'}
          </DialogDescription>
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
            onBack={() => setSelectedApp(null)}
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
