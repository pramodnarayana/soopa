import { type ApiProblem, Button, DataTable, StatusBadge, StatusTone } from '@soopa/ui';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Pencil, Plus, Trash2 } from 'lucide-react';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  useDeleteSimulatorEntityMutation,
  useSimulatorEntitiesQuery,
} from '../../application/use-simulator-queries';
import type { SimulatorEntity } from '../../domain/simulator';
import { CreateSimulatorEntityModal } from './CreateSimulatorEntityModal';

export interface SimulatorEntitiesSectionProps {
  readonly connectionId: string;
  readonly onProblem: (problem: ApiProblem | null) => void;
}

export function SimulatorEntitiesSection({
  connectionId,
  onProblem,
}: SimulatorEntitiesSectionProps): React.JSX.Element {
  const [modalOpen, setModalOpen] = useState(false);
  const [editingEntity, setEditingEntity] = useState<SimulatorEntity | null>(null);
  const entitiesView = useSimulatorEntitiesQuery(connectionId);
  const deleteEntityMutation = useDeleteSimulatorEntityMutation(connectionId);

  useEffect(() => {
    if (entitiesView.problem) {
      onProblem(entitiesView.problem);
    }
  }, [entitiesView.problem, onProblem]);

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
        accessorKey: 'recordsPerPull',
        header: 'Records per Pull',
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">{row.original.recordsPerPull}</span>
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
    [deleteEntityMutation.isPending, deleteEntityMutation.variables, handleDeleteEntity],
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
