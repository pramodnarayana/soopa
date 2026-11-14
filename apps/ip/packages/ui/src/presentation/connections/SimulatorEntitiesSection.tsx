import { type ApiProblem, Button, DataTable, StatusBadge, StatusTone } from '@soopa/ui';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Pencil, Plus, Radio, Trash2 } from 'lucide-react';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  useDeleteSimulatorEntityMutation,
  useSimulatePushMutation,
  useSimulatorEntitiesQuery,
} from '../../application/use-simulator-queries';
import type { SimulatorEntity } from '../../domain/simulator';
import { CreateSimulatorEntityModal } from './CreateSimulatorEntityModal';

export interface SimulatorEntitiesSectionProps {
  readonly connectionId: string;
  readonly onProblem: (problem: ApiProblem | null) => void;
}

function formatPushModeLabel(mode: string | undefined): string {
  switch (mode) {
    case 'MANUAL':
      return 'Manual (On-Demand)';
    case 'RANDOM_BURST':
      return 'Random Burst';
    case 'CONSTANT_PACED':
      return 'Constant Paced';
    case 'POISSON_JITTER':
      return 'Poisson Jitter';
    case 'CRON_BATCH':
      return 'Cron Batch';
    case 'CHAOS_FAULT':
      return 'Chaos Fault';
    case 'DIURNAL_WAVE':
      return 'Diurnal Wave';
    case 'THIN_PUSH':
      return 'Thin Push';
    default:
      return mode || 'Manual (On-Demand)';
  }
}

function formatPushCadenceSummary(entity: SimulatorEntity): string {
  const mode = entity.pushMode ?? 'MANUAL';
  const cfg = (entity.pushConfig ?? {}) as Record<string, unknown>;
  switch (mode) {
    case 'MANUAL': {
      const records =
        typeof cfg.records_per_push === 'number' && cfg.records_per_push >= 1
          ? cfg.records_per_push
          : 1;
      return `${records} msg${records === 1 ? '' : 's'} / click`;
    }
    case 'RANDOM_BURST': {
      const minB = cfg.min_batch ?? 1;
      const maxB = cfg.max_batch ?? 10;
      const intv = cfg.interval_seconds ?? 5;
      return `${minB}–${maxB} msgs / ${intv}s`;
    }
    case 'CONSTANT_PACED': {
      const rate = cfg.messages_per_second ?? 1;
      return `${rate} msg/s`;
    }
    case 'POISSON_JITTER': {
      const minD = cfg.min_delay_seconds ?? 1;
      const maxD = cfg.max_delay_seconds ?? 10;
      const minB = cfg.min_batch ?? 1;
      const maxB = cfg.max_batch ?? 5;
      return `${minB}–${maxB} msgs (${minD}–${maxD}s)`;
    }
    case 'CRON_BATCH': {
      const expr = cfg.cron_expression ?? '*/5 * * * *';
      const b = cfg.batch_size ?? 500;
      return `${b} msgs (${expr})`;
    }
    case 'CHAOS_FAULT': {
      const drop = cfg.drop_rate_percent ?? 20;
      return `${drop}% drops`;
    }
    case 'DIURNAL_WAVE': {
      const peak = cfg.peak_multiplier ?? 5;
      return `Circadian (${peak}x peak)`;
    }
    case 'THIN_PUSH': {
      const intv = cfg.interval_seconds ?? 2;
      return `Ping / ${intv}s`;
    }
    default:
      return '';
  }
}

function formatSimulateDataButtonLabel(entity: SimulatorEntity): string {
  const mode = entity.pushMode ?? 'MANUAL';
  const cfg = (entity.pushConfig ?? {}) as Record<string, unknown>;
  switch (mode) {
    case 'MANUAL': {
      const count =
        typeof cfg.records_per_push === 'number' && cfg.records_per_push >= 1
          ? cfg.records_per_push
          : 1;
      return `Simulate Data (${count})`;
    }
    case 'RANDOM_BURST': {
      const minB = cfg.min_batch ?? 1;
      const maxB = cfg.max_batch ?? 10;
      return `Simulate Data (${minB}–${maxB})`;
    }
    case 'CRON_BATCH': {
      const b = cfg.batch_size ?? 500;
      return `Simulate Data (${b})`;
    }
    case 'CHAOS_FAULT': {
      const b = cfg.batch_size ?? 5;
      return `Simulate Data (${b})`;
    }
    case 'CONSTANT_PACED':
      return 'Simulate Data (1)';
    case 'THIN_PUSH':
      return 'Simulate Data (Ping)';
    case 'POISSON_JITTER': {
      const minB = cfg.min_batch ?? 1;
      const maxB = cfg.max_batch ?? 5;
      return `Simulate Data (${minB}–${maxB})`;
    }
    case 'DIURNAL_WAVE':
      return 'Simulate Data (Wave)';
    default:
      return 'Simulate Data';
  }
}

function resolveEntityPushBatchCount(entity: SimulatorEntity): number {
  const mode = entity.pushMode ?? 'MANUAL';
  const cfg = (entity.pushConfig ?? {}) as Record<string, unknown>;
  switch (mode) {
    case 'MANUAL':
      return typeof cfg.records_per_push === 'number' && cfg.records_per_push >= 1
        ? Math.trunc(cfg.records_per_push)
        : 1;
    case 'CRON_BATCH':
      return typeof cfg.batch_size === 'number' && cfg.batch_size >= 1
        ? Math.trunc(cfg.batch_size)
        : 500;
    case 'CHAOS_FAULT':
      return typeof cfg.batch_size === 'number' && cfg.batch_size >= 1
        ? Math.trunc(cfg.batch_size)
        : 5;
    case 'CONSTANT_PACED':
      return 1;
    case 'THIN_PUSH':
      return 1;
    case 'RANDOM_BURST': {
      const minB = typeof cfg.min_batch === 'number' && cfg.min_batch >= 1 ? cfg.min_batch : 1;
      const maxB = typeof cfg.max_batch === 'number' && cfg.max_batch >= 1 ? cfg.max_batch : 10;
      const low = Math.min(minB, maxB);
      const high = Math.max(minB, maxB);
      return Math.floor(Math.random() * (high - low + 1)) + low;
    }
    case 'POISSON_JITTER': {
      const minB = typeof cfg.min_batch === 'number' && cfg.min_batch >= 1 ? cfg.min_batch : 1;
      const maxB = typeof cfg.max_batch === 'number' && cfg.max_batch >= 1 ? cfg.max_batch : 5;
      const low = Math.min(minB, maxB);
      const high = Math.max(minB, maxB);
      return Math.floor(Math.random() * (high - low + 1)) + low;
    }
    default:
      return 1;
  }
}

export function SimulatorEntitiesSection({
  connectionId,
  onProblem,
}: SimulatorEntitiesSectionProps): React.JSX.Element {
  const [modalOpen, setModalOpen] = useState(false);
  const [editingEntity, setEditingEntity] = useState<SimulatorEntity | null>(null);
  const entitiesView = useSimulatorEntitiesQuery(connectionId);
  const deleteEntityMutation = useDeleteSimulatorEntityMutation(connectionId);
  const simulatePushMutation = useSimulatePushMutation(connectionId);

  useEffect(() => {
    if (entitiesView.problem) {
      onProblem(entitiesView.problem);
    }
  }, [entitiesView.problem, onProblem]);

  const handleSimulateData = useCallback(
    async (entity: SimulatorEntity): Promise<void> => {
      onProblem(null);
      const count = resolveEntityPushBatchCount(entity);
      const res = await simulatePushMutation.mutateAsync({
        streamName: entity.entityName,
        count,
      });
      if (!res.ok) {
        onProblem(res.error);
        return;
      }
      toast.success(
        `Simulated data for "${entity.entityName}" (${res.value.recordsPushed} record${res.value.recordsPushed === 1 ? '' : 's'} ingested into L1).`,
      );
    },
    [simulatePushMutation, onProblem],
  );

  const handleDeleteEntity = useCallback(
    async (entity: SimulatorEntity): Promise<void> => {
      onProblem(null);
      const res = await deleteEntityMutation.mutateAsync(entity.id);
      if (!res.ok) {
        onProblem(res.error);
        return;
      }
      toast.success(`Removed entity "${entity.entityName}" from Simulator.`);
    },
    [deleteEntityMutation, onProblem],
  );

  const rows = useMemo(() => [...(entitiesView.data ?? [])], [entitiesView.data]);

  const columns = useMemo<ColumnDef<SimulatorEntity>[]>(
    () => [
      {
        accessorKey: 'entityName',
        header: 'Entity',
        cell: ({ row }) => (
          <span className="font-mono text-xs font-semibold text-foreground">
            {row.original.entityName}
          </span>
        ),
      },
      {
        accessorKey: 'primaryKeyField',
        header: 'Primary Key',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">
            {row.original.primaryKeyField}
          </span>
        ),
      },
      {
        accessorKey: 'cursorField',
        header: 'Cursor',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">
            {row.original.cursorField}
          </span>
        ),
      },
      {
        accessorKey: 'pushMode',
        header: 'Push Cadence',
        cell: ({ row }) => (
          <div className="flex flex-col gap-0.5">
            <span className="text-xs font-semibold text-foreground">
              {formatPushModeLabel(row.original.pushMode)}
            </span>
            <span className="font-mono text-[11px] text-muted-foreground">
              {formatPushCadenceSummary(row.original)}
            </span>
          </div>
        ),
      },
      {
        accessorKey: 'velocityMode',
        header: 'Velocity',
        cell: ({ row }) => (
          <StatusBadge label={row.original.velocityMode} tone={StatusTone.NEUTRAL} />
        ),
      },
      {
        accessorKey: 'version',
        header: 'Version',
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">v{row.original.version}</span>
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        meta: { className: 'text-right' },
        cell: ({ row }) => (
          <div className="flex items-center justify-end gap-1.5">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={
                simulatePushMutation.isPending &&
                simulatePushMutation.variables?.streamName === row.original.entityName
              }
              onClick={() => void handleSimulateData(row.original)}
              className="h-7 gap-1 px-2 text-xs"
            >
              <Radio className="h-3 w-3 text-primary" />
              <span>{formatSimulateDataButtonLabel(row.original)}</span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setEditingEntity(row.original);
                setModalOpen(true);
              }}
              className="h-7 gap-1 px-2 text-xs"
            >
              <Pencil className="h-3 w-3" />
              <span>Edit</span>
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={
                deleteEntityMutation.isPending && deleteEntityMutation.variables === row.original.id
              }
              onClick={() => void handleDeleteEntity(row.original)}
              className="h-7 gap-1 px-2 text-xs text-destructive hover:text-destructive"
            >
              <Trash2 className="h-3 w-3" />
              <span>Delete</span>
            </Button>
          </div>
        ),
      },
    ],
    [
      simulatePushMutation.isPending,
      simulatePushMutation.variables?.streamName,
      handleSimulateData,
      deleteEntityMutation.isPending,
      deleteEntityMutation.variables,
      handleDeleteEntity,
    ],
  );

  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-foreground">Simulator Entities</h2>
        <Button
          type="button"
          size="sm"
          onClick={() => {
            setEditingEntity(null);
            setModalOpen(true);
          }}
          className="h-8 gap-1.5 text-xs"
        >
          <Plus className="h-3.5 w-3.5" />
          <span>Create Entity</span>
        </Button>
      </div>

      <DataTable
        table={table}
        columnsLength={columns.length}
        isLoading={entitiesView.isLoading}
        dataLength={rows.length}
        ariaLabel="Simulator Entities"
        emptyTitle="No entities"
      />

      <CreateSimulatorEntityModal
        open={modalOpen}
        onOpenChange={(nextOpen) => {
          setModalOpen(nextOpen);
          if (!nextOpen) {
            setEditingEntity(null);
          }
        }}
        connectionId={connectionId}
        editingEntity={editingEntity}
        onProblem={onProblem}
      />
    </div>
  );
}
