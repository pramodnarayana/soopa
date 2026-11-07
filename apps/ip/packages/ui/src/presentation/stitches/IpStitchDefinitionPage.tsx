import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  DataTable,
  Skeleton,
  StatusBadge,
  StatusTone,
} from '@soopa/ui';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { ArrowLeft, GitFork } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { useStitchDefinitionQuery } from '../../application/use-stitch-queries';
import type { StitchNode } from '../../domain/stitch';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { IpPageHeader } from '../shared/IpPageHeader';
import { StitchDagCanvas } from './StitchDagCanvas';

export interface IpStitchDefinitionPageProps {
  readonly workflowId: string;
}

export function IpStitchDefinitionPage({ workflowId }: IpStitchDefinitionPageProps) {
  const { navigation } = useIpWorkspace();
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const defView = useStitchDefinitionQuery(workflowId);
  const definition = defView.data;

  const nodes = useMemo(() => [...(definition?.nodes ?? [])], [definition]);

  const columns = useMemo<ColumnDef<StitchNode>[]>(
    () => [
      {
        accessorKey: 'nodeKey',
        header: 'Node Key',
        cell: ({ row }) => <span className="font-mono font-semibold">{row.original.nodeKey}</span>,
      },
      {
        accessorKey: 'kind',
        header: 'Kind',
        cell: ({ row }) => <StatusBadge label={row.original.kind} tone={StatusTone.NEUTRAL} />,
      },
      {
        accessorKey: 'stepType',
        header: 'Handler / Wait Event',
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.waitEventKey ?? row.original.stepType}
          </span>
        ),
      },
      {
        id: 'parents',
        header: 'Parents & Edge Condition',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">
            {row.original.parents.length > 0
              ? `${row.original.parents.join(', ')} (${row.original.edgeCondition})`
              : 'Root Entry Node'}
          </span>
        ),
      },
      {
        accessorKey: 'effectPolicy',
        header: 'Effect Policy · Queue',
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.effectPolicy} · {row.original.queueName}
          </span>
        ),
      },
    ],
    [],
  );

  const table = useReactTable({
    data: nodes,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="space-y-6">
      <IpPageHeader
        eyebrow="Read-Only Topological Graph"
        title={definition ? `${definition.workflowId} (v${definition.version})` : workflowId}
        subtitle={
          definition?.description ??
          'Deterministic code-registered Stitch workflow DAG topology, wait gates, and side-effect policies.'
        }
        actions={
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => navigation.toStitches()}
            className="gap-1.5"
          >
            <ArrowLeft className="h-4 w-4" />
            <span>Stitches</span>
          </Button>
        }
      />

      <ApiProblemBanner problem={defView.problem} onRetry={() => void defView.refetch()} />

      {defView.isLoading || !definition ? (
        <Skeleton className="h-80 w-full rounded-xl" />
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Topological Execution Graph</CardTitle>
              <CardDescription>
                Solar Yellow headers denote TASK handlers; Copper headers denote WAIT_FOR_EVENT
                condition gates; dashed edges denote ON_FAILURE compensation branches.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <StitchDagCanvas
                nodes={definition.nodes}
                selectedNodeKey={selectedNodeKey}
                onSelectNode={setSelectedNodeKey}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Node Specifications ({nodes.length})</CardTitle>
            </CardHeader>
            <CardContent>
              <DataTable
                table={table}
                columnsLength={columns.length}
                dataLength={nodes.length}
                ariaLabel="Stitch DAG node specifications"
                emptyIcon={<GitFork className="h-6 w-6" />}
                onRowClick={(row) => setSelectedNodeKey(row.original.nodeKey)}
              />
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
