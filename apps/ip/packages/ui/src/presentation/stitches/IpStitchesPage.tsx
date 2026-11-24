import {
  Button,
  CopyableIdPill,
  DataTable,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  StatusBadge,
  StatusTone,
  Tabs,
  TabsList,
  TabsTrigger,
} from '@soopa/ui';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import {
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  Plus,
  Search,
  Send,
  Sparkles,
  Trash2,
  Workflow,
} from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  useStitchDefinitionsQuery,
  useStitchesQuery,
  useStitchRunsQuery,
  useToggleStitchStateMutation,
} from '../../application/use-stitch-queries';
import type { Stitch, StitchRun } from '../../domain/stitch';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { IpPageHeader } from '../shared/IpPageHeader';
import { formatRelativeTimestamp, mapStitchRunStatusTone } from '../shared/status-mapping';
import {
  DeleteStitchModal,
  DispatchCanonicalEventModal,
  EditStitchModal,
  RegisterStitchModal,
} from './StitchModals';

export type StitchStatusFilter = 'ALL' | 'ACTIVE' | 'PAUSED' | 'SUSPENDED';

export function ActiveStitchesTable({
  stitches,
  isLoading,
  onOpenDefinition,
  onEditStitch,
  onDeleteStitch,
  onToggleState,
  onDispatchEvent,
}: {
  readonly stitches: readonly Stitch[];
  readonly isLoading: boolean;
  readonly onOpenDefinition: (workflowId: string) => void;
  readonly onEditStitch: (stitch: Stitch) => void;
  readonly onDeleteStitch: (stitch: Stitch) => void;
  readonly onToggleState: (stitch: Stitch) => void;
  readonly onDispatchEvent: (stitch: Stitch) => void;
}) {
  const rows = useMemo(() => [...stitches], [stitches]);
  const columns = useMemo<ColumnDef<Stitch>[]>(
    () => [
      {
        accessorKey: 'name',
        header: 'Stitch Pipeline',
        cell: ({ row }) => {
          const displayName = row.original.name?.trim() || row.original.workflowId;
          const canonicalType = row.original.canonicalEventType;
          const domain = canonicalType ? canonicalType.split('.')[0] : 'general';

          return (
            <div className="flex flex-col gap-1 py-0.5">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-xs text-foreground hover:text-primary transition-colors">
                  {displayName}
                </span>
                <span className="inline-flex items-center gap-1 font-mono text-[10px] font-medium px-1.5 py-0.2 rounded border bg-primary/10 text-primary border-primary/20">
                  <Workflow className="h-3 w-3" />
                  <span>{domain}</span>
                </span>
              </div>
              <span className="font-mono text-[11px] text-muted-foreground">
                {row.original.workflowId} (v{row.original.workflowVersion})
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: 'canonicalEventType',
        header: 'Canonical Standard',
        cell: ({ row }) => (
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-xs font-medium text-foreground">
              {row.original.canonicalEventType}
            </span>
            <span className="font-mono text-[10px] text-muted-foreground">
              Key: {row.original.idempotencyKeyField}
            </span>
          </div>
        ),
      },
      {
        accessorKey: 'mappingSpecId',
        header: 'Mapping Spec',
        cell: ({ row }) =>
          row.original.mappingSpecId ? (
            <CopyableIdPill value={row.original.mappingSpecId} />
          ) : (
            <span className="text-muted-foreground text-xs">—</span>
          ),
      },
      {
        accessorKey: 'isTrigger',
        header: 'Execution Trigger',
        cell: ({ row }) => (
          <StatusBadge
            label={
              row.original.isTrigger
                ? 'DAG Trigger'
                : `Gate: ${row.original.conditionEventKey ?? 'wait'}`
            }
            tone={row.original.isTrigger ? StatusTone.HEALTHY : StatusTone.WARNING}
          />
        ),
      },
      {
        accessorKey: 'isActive',
        header: 'Status',
        cell: ({ row }) => (
          <StatusBadge
            label={row.original.isActive ? 'ACTIVE' : 'PAUSED'}
            tone={row.original.isActive ? StatusTone.HEALTHY : StatusTone.NEUTRAL}
          />
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        cell: ({ row }) => {
          const stitch = row.original;
          return (
            <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
                title={stitch.isActive ? 'Pause pipeline' : 'Activate pipeline'}
                onClick={() => onToggleState(stitch)}
              >
                {stitch.isActive ? (
                  <Pause className="h-3.5 w-3.5 text-amber-500" />
                ) : (
                  <Play className="h-3.5 w-3.5 text-emerald-500" />
                )}
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 p-0"
                    aria-label="Stitch actions"
                  >
                    <MoreHorizontal className="h-3.5 w-3.5" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="text-xs">
                  <DropdownMenuItem
                    onClick={() => onEditStitch(stitch)}
                    className="gap-2 cursor-pointer"
                  >
                    <Pencil className="h-3.5 w-3.5 text-muted-foreground" />
                    <span>Edit Pipeline</span>
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => onToggleState(stitch)}
                    className="gap-2 cursor-pointer"
                  >
                    {stitch.isActive ? (
                      <>
                        <Pause className="h-3.5 w-3.5 text-amber-500" />
                        <span>Pause Pipeline</span>
                      </>
                    ) : (
                      <>
                        <Play className="h-3.5 w-3.5 text-emerald-500" />
                        <span>Activate Pipeline</span>
                      </>
                    )}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => onDispatchEvent(stitch)}
                    className="gap-2 cursor-pointer"
                  >
                    <Send className="h-3.5 w-3.5 text-muted-foreground" />
                    <span>Dispatch Test Event</span>
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() => onDeleteStitch(stitch)}
                    className="gap-2 text-destructive focus:text-destructive cursor-pointer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    <span>Delete Pipeline</span>
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          );
        },
      },
    ],
    [onDeleteStitch, onDispatchEvent, onEditStitch, onToggleState],
  );

  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <DataTable
      table={table}
      columnsLength={columns.length}
      isLoading={isLoading}
      dataLength={rows.length}
      ariaLabel="Active Stitches"
      emptyIcon={<Workflow className="h-6 w-6" />}
      emptyTitle="No Stitches Match Filter"
      emptyDescription="No stitches match the current filter selection."
      onRowClick={(row) => onOpenDefinition(row.original.workflowId)}
    />
  );
}

export function StitchRunsTable({
  runs,
  isLoading,
  onOpenRun,
}: {
  readonly runs: readonly StitchRun[];
  readonly isLoading: boolean;
  readonly onOpenRun: (runId: string) => void;
}) {
  const rows = useMemo(() => [...runs], [runs]);

  const columns = useMemo<ColumnDef<StitchRun>[]>(
    () => [
      {
        accessorKey: 'runId',
        header: 'Run ID',
        cell: ({ row }) => <span className="font-mono text-xs">{row.original.runId}</span>,
      },
      {
        accessorKey: 'workflowId',
        header: 'Workflow ID',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-foreground font-medium">
            {row.original.workflowId} (v{row.original.workflowVersion})
          </span>
        ),
      },
      {
        accessorKey: 'status',
        header: 'Run Status',
        cell: ({ row }) => {
          const tone = mapStitchRunStatusTone(row.original.status);
          return <StatusBadge label={row.original.status} tone={tone} />;
        },
      },
      {
        accessorKey: 'createdAt',
        header: 'Triggered',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">
            {formatRelativeTimestamp(row.original.createdAt)}
          </span>
        ),
      },
    ],
    [],
  );

  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <DataTable
      table={table}
      columnsLength={columns.length}
      isLoading={isLoading}
      dataLength={rows.length}
      ariaLabel="Durable Stitch Runs"
      emptyIcon={<Workflow className="h-6 w-6" />}
      emptyTitle="No Stitch Runs Executed Yet"
      emptyDescription="No stitch runs executed yet."
      onRowClick={(row) => onOpenRun(row.original.runId)}
    />
  );
}

export function IpStitchesPage() {
  const { navigation } = useIpWorkspace();
  const [statusFilter, setStatusFilter] = useState<StitchStatusFilter>('ALL');
  const [domainFilter, setDomainFilter] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [mainView, setMainView] = useState<'stitches' | 'runs'>('stitches');

  const [registerOpen, setRegisterOpen] = useState(false);
  const [editStitch, setEditStitch] = useState<Stitch | null>(null);
  const [deleteStitch, setDeleteStitch] = useState<Stitch | null>(null);
  const [dispatchOpen, setDispatchOpen] = useState(false);
  const [dispatchCanonicalEventType, setDispatchCanonicalEventType] = useState<string | undefined>(
    undefined,
  );

  const stitchesView = useStitchesQuery();
  const runsView = useStitchRunsQuery();
  const defsView = useStitchDefinitionsQuery();
  const toggleMutation = useToggleStitchStateMutation();

  const handleToggleState = async (stitch: Stitch) => {
    try {
      await toggleMutation.mutateAsync({
        stitchId: stitch.id,
        isActive: !stitch.isActive,
      });
      toast.success(stitch.isActive ? 'Pipeline paused' : 'Pipeline activated');
    } catch {
      toast.error('Failed to update pipeline state');
    }
  };

  const handleOpenDispatchForStitch = (stitch: Stitch) => {
    setDispatchCanonicalEventType(stitch.canonicalEventType);
    setDispatchOpen(true);
  };

  const allStitches = stitchesView.data ?? [];

  const availableDomains = useMemo(() => {
    const domains = new Set<string>();
    for (const stitch of allStitches) {
      if (stitch.canonicalEventType) {
        domains.add(stitch.canonicalEventType.split('.')[0]);
      }
    }
    return Array.from(domains).sort();
  }, [allStitches]);

  // Filter stitches by status, domain, and search query
  const filteredStitches = useMemo(() => {
    return allStitches.filter((stitch) => {
      // 1. Status Filter
      if (statusFilter === 'ACTIVE' && !stitch.isActive) return false;
      if (statusFilter === 'PAUSED' && stitch.isActive) return false;
      if (statusFilter === 'SUSPENDED') {
        // Reserved for suspended pipelines or inactive with error
        if (stitch.isActive) return false;
      }

      // 2. Domain Filter
      if (domainFilter !== 'ALL') {
        const stitchDomain = stitch.canonicalEventType
          ? stitch.canonicalEventType.split('.')[0]
          : '';
        if (stitchDomain !== domainFilter) return false;
      }

      // 3. Search Query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const matchesName = (stitch.name ?? '').toLowerCase().includes(q);
        const matchesWorkflow = stitch.workflowId.toLowerCase().includes(q);
        const matchesCanonical = stitch.canonicalEventType.toLowerCase().includes(q);
        if (!matchesName && !matchesWorkflow && !matchesCanonical) return false;
      }

      return true;
    });
  }, [allStitches, statusFilter, domainFilter, searchQuery]);

  const activeCount = useMemo(() => allStitches.filter((s) => s.isActive).length, [allStitches]);
  const pausedCount = useMemo(() => allStitches.filter((s) => !s.isActive).length, [allStitches]);

  const combinedProblem = stitchesView.problem ?? runsView.problem ?? defsView.problem;

  return (
    <div className="space-y-6">
      <IpPageHeader
        title="Stitches / Workflows"
        actions={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setDispatchCanonicalEventType(undefined);
                setDispatchOpen(true);
              }}
              className="gap-1.5"
            >
              <Send className="h-3.5 w-3.5" />
              <span>Test Event Dispatch</span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setRegisterOpen(true)}
              className="gap-1.5"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>Register Stitch</span>
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => {
                if (navigation.toStitchMapper) {
                  navigation.toStitchMapper();
                }
              }}
              className="gap-1.5"
            >
              <Sparkles className="h-3.5 w-3.5" />
              <span>Stitch &amp; Field Mapper</span>
            </Button>
          </div>
        }
      />

      <ApiProblemBanner problem={combinedProblem} />

      {/* Primary Toolbar: Status Filter Tabs & Search */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-1 border-b border-border/60">
        <div className="flex items-center gap-2">
          {/* Main View Toggle: Stitches vs Execution Runs */}
          <Tabs value={mainView} onValueChange={(val) => setMainView(val as 'stitches' | 'runs')}>
            <TabsList className="h-8">
              <TabsTrigger value="stitches" className="text-xs px-3">
                Stitches ({allStitches.length})
              </TabsTrigger>
              <TabsTrigger value="runs" className="text-xs px-3">
                Execution Runs ({(runsView.data ?? []).length})
              </TabsTrigger>
            </TabsList>
          </Tabs>

          {mainView === 'stitches' && (
            <div className="hidden sm:flex items-center border-l border-border/80 pl-3 ml-1 gap-1">
              <Button
                type="button"
                variant={statusFilter === 'ALL' ? 'secondary' : 'ghost'}
                size="sm"
                onClick={() => setStatusFilter('ALL')}
                className="h-7 text-xs px-2.5"
              >
                All ({allStitches.length})
              </Button>
              <Button
                type="button"
                variant={statusFilter === 'ACTIVE' ? 'secondary' : 'ghost'}
                size="sm"
                onClick={() => setStatusFilter('ACTIVE')}
                className="h-7 text-xs px-2.5 text-emerald-600 dark:text-emerald-400"
              >
                Active ({activeCount})
              </Button>
              <Button
                type="button"
                variant={statusFilter === 'PAUSED' ? 'secondary' : 'ghost'}
                size="sm"
                onClick={() => setStatusFilter('PAUSED')}
                className="h-7 text-xs px-2.5 text-muted-foreground"
              >
                Paused ({pausedCount})
              </Button>
              <Button
                type="button"
                variant={statusFilter === 'SUSPENDED' ? 'secondary' : 'ghost'}
                size="sm"
                onClick={() => setStatusFilter('SUSPENDED')}
                className="h-7 text-xs px-2.5 text-amber-500"
              >
                Suspended (0)
              </Button>
            </div>
          )}
        </div>

        {mainView === 'stitches' && (
          <div className="flex items-center gap-2">
            {availableDomains.length > 0 && (
              <Select value={domainFilter} onValueChange={(val) => setDomainFilter(val)}>
                <SelectTrigger className="h-8 text-xs w-40">
                  <SelectValue placeholder="All Domains" />
                </SelectTrigger>
                <SelectContent className="text-xs">
                  <SelectItem value="ALL">All Domains</SelectItem>
                  {availableDomains.map((domain) => (
                    <SelectItem key={domain} value={domain}>
                      {domain.toUpperCase()} Domain
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}

            <div className="relative">
              <Search className="h-3.5 w-3.5 text-muted-foreground absolute left-2.5 top-1/2 -translate-y-1/2" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search stitches..."
                className="h-8 pl-8 text-xs w-48 sm:w-56"
              />
            </div>
          </div>
        )}
      </div>

      {/* Main Content Area */}
      {mainView === 'stitches' ? (
        <ActiveStitchesTable
          stitches={filteredStitches}
          isLoading={stitchesView.isLoading}
          onOpenDefinition={(wfId) => navigation.toStitchDefinition(wfId)}
          onEditStitch={(s) => setEditStitch(s)}
          onDeleteStitch={(s) => setDeleteStitch(s)}
          onToggleState={(s) => void handleToggleState(s)}
          onDispatchEvent={handleOpenDispatchForStitch}
        />
      ) : (
        <StitchRunsTable
          runs={runsView.data ?? []}
          isLoading={runsView.isLoading}
          onOpenRun={(runId) => navigation.toStitchRun(runId)}
        />
      )}

      <RegisterStitchModal
        open={registerOpen}
        onOpenChange={setRegisterOpen}
        definitions={defsView.data ?? []}
      />

      <EditStitchModal
        open={Boolean(editStitch)}
        onOpenChange={(open) => {
          if (!open) setEditStitch(null);
        }}
        stitch={editStitch}
      />

      <DeleteStitchModal
        open={Boolean(deleteStitch)}
        onOpenChange={(open) => {
          if (!open) setDeleteStitch(null);
        }}
        stitch={deleteStitch}
      />

      <DispatchCanonicalEventModal
        open={dispatchOpen}
        onOpenChange={setDispatchOpen}
        onOpenRun={(runId) => navigation.toStitchRun(runId)}
        defaultCanonicalEventType={dispatchCanonicalEventType}
      />
    </div>
  );
}
