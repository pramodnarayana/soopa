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
  StatusBadge,
  StatusTone,
} from '@soopa/ui';
import React, { useMemo, useState } from 'react';
import { toast } from 'sonner';
import { useCatalogAppSpecQuery } from '../../application/use-catalog-queries';
import {
  useDeactivateConnectionMutation,
  useDeleteConnectionMutation,
  useRelinkConnectionMutation,
  useUpdateConnectionMutation,
} from '../../application/use-connection-queries';
import type { Connection } from '../../domain/connection';
import { ConnectionStatus, ConnectorPropertyKey } from '../../domain/enums';
import { formatRelativeTimestamp } from '../shared/status-mapping';
import {
  isPropertyVisible,
  isSecretConnectorProperty,
  resolvePropertyLabel,
  SingleSpecPropertyControl,
  splitSpecFormValues,
} from './SpecFormRenderer';

export interface ConnectionOverviewTabProps {
  readonly connection: Connection;
  readonly onProblem: (problem: ApiProblem | null) => void;
  readonly onDeactivated: () => void;
  readonly onDeleted?: () => void;
}

export function ConnectionOverviewTab({
  connection,
  onProblem,
  onDeactivated,
  onDeleted,
}: ConnectionOverviewTabProps) {
  const [name, setName] = useState(connection.name);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const specView = useCatalogAppSpecQuery(connection.appId);
  const relinkMutation = useRelinkConnectionMutation(connection.id);
  const updateMutation = useUpdateConnectionMutation(connection.id);
  const deactivateMutation = useDeactivateConnectionMutation(connection.id);
  const deleteMutation = useDeleteConnectionMutation(connection.id);
  const isDeactivated = connection.status === ConnectionStatus.DEACTIVATED;
  const isSaving = relinkMutation.isPending || updateMutation.isPending;

  const allProperties = specView.data?.properties ?? [];

  const [formValues, setFormValues] = useState<Record<string, unknown>>(() => ({
    ...connection.publicConfig,
    [ConnectorPropertyKey.AUTH_TYPE]: connection.authType,
  }));

  const visibleProperties = useMemo(
    () => allProperties.filter((prop) => isPropertyVisible(prop, formValues, allProperties)),
    [allProperties, formValues],
  );

  const isDirty = useMemo(() => {
    if (name.trim() !== connection.name) return true;
    if (formValues[ConnectorPropertyKey.AUTH_TYPE] !== connection.authType) return true;
    for (const [key, val] of Object.entries(formValues)) {
      if (key === ConnectorPropertyKey.AUTH_TYPE) continue;
      if (val !== connection.publicConfig[key]) return true;
    }
    for (const key of Object.keys(connection.publicConfig)) {
      if (key === ConnectorPropertyKey.AUTH_TYPE) continue;
      if (!(key in formValues) || formValues[key] === '' || formValues[key] === undefined) {
        if (connection.publicConfig[key] !== undefined && connection.publicConfig[key] !== '') {
          return true;
        }
      }
    }
    return false;
  }, [name, formValues, connection]);

  const handleSave = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    onProblem(null);

    const { rawCredentials } = splitSpecFormValues(allProperties, formValues);
    const hasSecretPatch = Object.keys(rawCredentials).length > 0;

    // Preserve unexposed public config keys and omit cleared keys
    const mergedPublicConfig: Record<string, unknown> = {
      ...connection.publicConfig,
    };
    for (const prop of allProperties) {
      if (isSecretConnectorProperty(prop)) continue;
      const val = formValues[prop.name];
      if (val === undefined || val === '') {
        delete mergedPublicConfig[prop.name];
      } else {
        mergedPublicConfig[prop.name] = val;
      }
    }
    if (formValues[ConnectorPropertyKey.AUTH_TYPE]) {
      mergedPublicConfig[ConnectorPropertyKey.AUTH_TYPE] =
        formValues[ConnectorPropertyKey.AUTH_TYPE];
    }

    const mutation = isDeactivated ? relinkMutation : updateMutation;
    const res = await mutation.mutateAsync({
      newName: name.trim() || connection.name,
      updatedRawCredentials: hasSecretPatch ? rawCredentials : null,
      updatedPublicConfig: Object.keys(mergedPublicConfig).length > 0 ? mergedPublicConfig : null,
    });
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    toast.success(isDeactivated ? 'Connection updated and reactivated.' : 'Connection updated.');
  };

  const handleDeactivate = async (): Promise<void> => {
    onProblem(null);
    const res = await deactivateMutation.mutateAsync();
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    toast.success('Connection deactivated.');
    onDeactivated();
  };

  const handleDelete = async (): Promise<void> => {
    onProblem(null);
    const res = await deleteMutation.mutateAsync(connection.id);
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    toast.success('Connection deleted. Historical entities and synced data preserved.');
    setDeleteDialogOpen(false);
    onDeleted?.();
  };

  const statusTone =
    connection.status === ConnectionStatus.ACTIVE
      ? StatusTone.HEALTHY
      : connection.status === ConnectionStatus.PENDING_AUTH
        ? StatusTone.WARNING
        : StatusTone.NEUTRAL;

  return (
    <div className="p-6 bg-muted/20 rounded-xl border border-border">
      <form onSubmit={(e) => void handleSave(e)} className="space-y-6">
        <div className="flex justify-between items-center pb-4 border-b border-border">
          <h4 className="text-xs font-semibold text-foreground uppercase tracking-wider">
            Connection Details
          </h4>
          <div className="flex items-center gap-2">
            <Button type="submit" size="sm" disabled={isSaving || !isDirty} className="text-xs">
              {isSaving ? 'Saving...' : 'Save Changes'}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={deactivateMutation.isPending || connection.deactivatedAt !== null}
              onClick={() => void handleDeactivate()}
              className="text-xs"
            >
              {connection.deactivatedAt
                ? 'Already Deactivated'
                : deactivateMutation.isPending
                  ? 'Deactivating...'
                  : 'Deactivate Connection'}
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              disabled={deleteMutation.isPending}
              onClick={() => setDeleteDialogOpen(true)}
              className="text-xs"
            >
              Delete Connection
            </Button>
          </div>
        </div>

        {/* Editable form fields first, starting with Name */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <div className="space-y-2">
            <Label htmlFor="conn-name">Name</Label>
            <Input
              id="conn-name"
              name="connection_name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          {visibleProperties.map((prop) => {
            const displayLabel = resolvePropertyLabel(prop, connection.authType);
            return (
              <div key={prop.name} className="space-y-2">
                <Label htmlFor={`spec-${prop.name}`} className="flex items-center gap-1">
                  <span>{displayLabel}</span>
                  {prop.required && !isSecretConnectorProperty(prop) ? (
                    <span className="text-status-critical-fg">*</span>
                  ) : null}
                  {prop.required && isSecretConnectorProperty(prop) ? (
                    <span className="text-xs font-normal text-muted-foreground">(stored)</span>
                  ) : null}
                </Label>
                <SingleSpecPropertyControl
                  prop={prop}
                  rawValue={formValues[prop.name]}
                  onChange={(nextVal) =>
                    setFormValues((prev) => ({ ...prev, [prop.name]: nextVal }))
                  }
                  currentAuthType={connection.authType}
                  isEditing={true}
                />
              </div>
            );
          })}
        </div>

        {/* Readonly fields arranged after editable fields */}
        <div className="grid grid-cols-2 gap-6 text-xs sm:grid-cols-4">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Connector</Label>
            <div className="font-semibold text-sm text-foreground">
              {specView.data?.displayName || connection.appId}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Status</Label>
            <div>
              <StatusBadge label={connection.status} tone={statusTone} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Auth Strategy</Label>
            <div className="font-mono text-sm text-foreground">{connection.authType}</div>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Created</Label>
            <div className="text-sm text-foreground">
              {formatRelativeTimestamp(connection.createdAt)}
            </div>
          </div>
          {connection.lastRefreshedAt ? (
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Last Refreshed</Label>
              <div className="text-sm text-foreground">
                {formatRelativeTimestamp(connection.lastRefreshedAt)}
              </div>
            </div>
          ) : null}
        </div>
      </form>

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete Connection</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete{' '}
              <span className="font-semibold text-foreground">{connection.name}</span>? Historical
              entities and synced data will remain preserved.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="mt-4 gap-2 sm:gap-0">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={deleteMutation.isPending}
              onClick={() => setDeleteDialogOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              disabled={deleteMutation.isPending}
              onClick={() => void handleDelete()}
            >
              {deleteMutation.isPending ? 'Deleting...' : 'Delete Connection'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
