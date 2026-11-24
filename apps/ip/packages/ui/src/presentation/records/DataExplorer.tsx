import { Button, Card, SearchableSelect, type SearchableSelectOption } from '@soopa/ui';
import { FileSpreadsheet, Layers, RefreshCw } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { useConnectionEntitiesQuery } from '../../application/use-connection-entity-queries';
import {
  useNormalizedRecordsQuery,
  useOutboundRecordsQuery,
} from '../../application/use-record-queries';
import type { NormalizedRecord } from '../../domain/trace';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { RecordsTable } from './RecordsTable';

export interface DataExplorerProps {
  readonly connectionId?: string;
  readonly initialEntityKey?: string;
  readonly onOpenTraceDetail?: (traceId: string) => void;
  readonly onOpenTrace?: (traceId: string) => void;
  readonly onOpenTraceStitches?: (traceId: string) => void;
}

interface EntityGroup {
  readonly key: string;
  readonly displayName: string;
  readonly records: readonly NormalizedRecord[];
}

export function deriveFriendlyEntityName(typeKey: string): string {
  const lower = typeKey.toLowerCase();
  if (lower.includes('invoice')) return 'Invoices';
  if (lower.includes('order')) return 'Orders';
  if (lower.includes('telemetry') || lower.includes('reading') || lower.includes('interval')) {
    return 'Interval Readings';
  }
  if (lower.includes('load') || lower.includes('tender') || lower.includes('shipment')) {
    return 'Shipment Loads';
  }
  if (lower.includes('customer')) return 'Customers';
  if (lower.includes('device')) return 'Devices';

  // Fallback: strip canonical/domain prefixes and version suffixes
  return typeKey
    .replace(/^canonical[._]/i, '')
    .replace(/^domain[._]/i, '')
    .replace(/[._]v\d+$/i, '')
    .replace(/[._]/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

export function DataExplorer({
  connectionId,
  initialEntityKey,
  onOpenTraceDetail,
  onOpenTrace,
  onOpenTraceStitches,
}: DataExplorerProps) {
  const [selectedEntityKey, setSelectedEntityKey] = useState<string>(initialEntityKey ?? '');

  const handleOpenTrace = onOpenTraceDetail ?? onOpenTrace;

  // Queries
  const normalizedQuery = useNormalizedRecordsQuery({ connectionId, limit: 100 });
  const outboundQuery = useOutboundRecordsQuery({ connectionId, limit: 100 });
  const connectionEntitiesView = useConnectionEntitiesQuery(
    connectionId ?? '',
    Boolean(connectionId),
  );

  const allRecords = normalizedQuery.data ?? [];
  const outboundRecords = outboundQuery.data ?? [];
  const configuredEntities = connectionEntitiesView.data ?? [];

  // Group records by business entity
  const entityGroups = useMemo<readonly EntityGroup[]>(() => {
    const groupsMap = new Map<string, NormalizedRecord[]>();

    // 1. Seed standard enterprise domain models so they are ALWAYS available in dropdown
    const standardEntities = [
      'Orders',
      'Invoices',
      'Interval Readings',
      'Shipment Loads',
      'Customers',
    ];
    for (const name of standardEntities) {
      groupsMap.set(name, []);
    }

    // 2. Register any Control Plane configured connection entities
    for (const ent of configuredEntities) {
      const name = deriveFriendlyEntityName(ent.streamName);
      if (!groupsMap.has(name)) {
        groupsMap.set(name, []);
      }
    }

    // 3. Map fetched records into their matching entity group
    for (const record of allRecords) {
      const friendlyName = deriveFriendlyEntityName(record.canonicalType);
      const list = groupsMap.get(friendlyName) ?? [];
      list.push(record);
      groupsMap.set(friendlyName, list);
    }

    return Array.from(groupsMap.entries()).map(([name, recs]) => ({
      key: name,
      displayName: name,
      records: recs,
    }));
  }, [allRecords, configuredEntities]);

  // Options for single SearchableSelect dropdown
  const entityOptions: readonly SearchableSelectOption[] = useMemo(() => {
    return entityGroups.map((group) => ({
      value: group.key,
      label: (
        <div className="flex items-center justify-between w-full gap-3 py-0.5">
          <span className="font-medium text-foreground">{group.displayName}</span>
          <span className="text-[11px] font-mono text-muted-foreground px-1.5 py-0.5 bg-muted rounded-full">
            {group.records.length} {group.records.length === 1 ? 'record' : 'records'}
          </span>
        </div>
      ),
      searchString: `${group.displayName} ${group.key}`,
    }));
  }, [entityGroups]);

  // Active entity selection - Action-driven only (No default fallback)
  const activeEntity = useMemo(() => {
    if (!selectedEntityKey) return null;
    return entityGroups.find((g) => g.key === selectedEntityKey) ?? null;
  }, [entityGroups, selectedEntityKey]);

  return (
    <div className="space-y-6">
      <ApiProblemBanner
        problem={normalizedQuery.problem}
        onRetry={() => void normalizedQuery.refetch()}
      />

      {/* Top Toolbar: Action-Driven Searchable Entity Combobox */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border pb-4">
        <div className="flex items-center gap-3 w-full sm:max-w-md">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
            Business Entity:
          </span>
          <div className="flex-1">
            <SearchableSelect
              options={entityOptions}
              value={activeEntity?.key ?? ''}
              onChange={(val) => setSelectedEntityKey(val)}
              placeholder="Select an entity to explore..."
              searchPlaceholder="Type entity name to search..."
              emptyText="No matching entities found."
            />
          </div>
        </div>

        {activeEntity ? (
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground font-mono">
              Viewing{' '}
              <span className="font-semibold text-foreground">{activeEntity.displayName}</span> ·{' '}
              <span className="font-semibold text-foreground">{activeEntity.records.length}</span>{' '}
              records
            </span>
            <Button
              type="button"
              variant="ghost"
              size="xs"
              onClick={() => setSelectedEntityKey('')}
              className="text-xs text-muted-foreground hover:text-foreground h-7"
            >
              Clear Selection
            </Button>
          </div>
        ) : null}
      </div>

      {/* Primary View: Selected Business Entity Table or Minimal Placeholder */}
      {activeEntity === null ? (
        <Card className="rounded-xl border border-dashed border-border p-12 text-center bg-card/20">
          <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-muted/60 text-muted-foreground mb-3">
            <Layers className="h-5 w-5" />
          </div>
          <h3 className="text-sm font-semibold text-foreground">No Entity Selected</h3>
          <p className="text-xs text-muted-foreground mt-1">
            Select a business entity from the dropdown above to view records.
          </p>
        </Card>
      ) : activeEntity.records.length > 0 ? (
        <RecordsTable
          entityName={activeEntity.displayName}
          records={activeEntity.records}
          isLoading={normalizedQuery.isLoading}
          outboundRecords={outboundRecords}
          onOpenTraceDetail={handleOpenTrace}
          onOpenTraceStitches={onOpenTraceStitches}
        />
      ) : (
        <Card className="rounded-xl border border-dashed border-border p-12 text-center bg-card/50">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-muted/60 text-muted-foreground mb-4">
            <FileSpreadsheet className="h-6 w-6" />
          </div>
          <h3 className="text-sm font-semibold text-foreground mb-1">
            No synced records found for {activeEntity.displayName}
          </h3>
          <p className="text-xs text-muted-foreground max-w-md mx-auto mb-4">
            No business records for {activeEntity.displayName} have been ingested under the current
            connection filter. Synced records appear automatically upon inbound webhook receipt or
            scheduled extraction.
          </p>
          <div className="flex items-center justify-center gap-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void normalizedQuery.refetch()}
              className="text-xs gap-1.5"
            >
              <RefreshCw className="h-3 w-3" />
              <span>Refresh Records</span>
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setSelectedEntityKey('')}
              className="text-xs"
            >
              Choose Another Entity
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}

// Deprecated alias for backward-compatibility during phase transition
export {
  DataExplorer as BusinessDataExplorer,
  type DataExplorerProps as BusinessDataExplorerProps,
};
