import {
  Button,
  CopyableIdPill,
  DataTable,
  StatusBadge,
  StatusTone,
  Tabs,
  TabsList,
  TabsTrigger,
} from '@soopa/ui';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Cable, Plus } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { useConnectionsQuery } from '../../application/use-connection-queries';
import type { Connection } from '../../domain/connection';
import { ConnectionStatus } from '../../domain/enums';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { IpPageHeader } from '../shared/IpPageHeader';
import { formatRelativeTimestamp, mapConnectionStatusTone } from '../shared/status-mapping';
import { CreateConnectionModal } from './CreateConnectionModal';

const ALL_TAB = 'ALL';

export function IpConnectionsPage() {
  const { navigation } = useIpWorkspace();
  const [statusTab, setStatusTab] = useState<string>(ALL_TAB);
  const [createOpen, setCreateOpen] = useState(false);

  const connectionsView = useConnectionsQuery(statusTab === ALL_TAB ? undefined : statusTab);
  const rows = useMemo(() => [...(connectionsView.data ?? [])], [connectionsView.data]);

  const columns = useMemo<ColumnDef<Connection>[]>(
    () => [
      {
        accessorKey: 'name',
        header: 'Connection',
        cell: ({ row }) => (
          <div>
            <div className="font-semibold text-foreground">{row.original.name}</div>
            <div className="font-mono text-xs text-muted-foreground">{row.original.appId}</div>
          </div>
        ),
      },
      {
        accessorKey: 'authType',
        header: 'Auth Strategy',
        cell: ({ row }) => <StatusBadge label={row.original.authType} tone={StatusTone.NEUTRAL} />,
      },
      {
        accessorKey: 'connectionFingerprint',
        header: 'SHA-256 Fingerprint',
        cell: ({ row }) => (
          <CopyableIdPill value={row.original.connectionFingerprint} truncateLength={16} />
        ),
      },
      {
        accessorKey: 'status',
        header: 'Health',
        cell: ({ row }) => (
          <StatusBadge
            label={row.original.status}
            tone={mapConnectionStatusTone(row.original.status)}
          />
        ),
      },
      {
        accessorKey: 'tokenExpiresAt',
        header: 'Token Expiry',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            {row.original.tokenExpiresAt
              ? formatRelativeTimestamp(row.original.tokenExpiresAt)
              : 'Non-expiring'}
          </span>
        ),
      },
      {
        accessorKey: 'updatedAt',
        header: 'Updated',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            {formatRelativeTimestamp(row.original.updatedAt)}
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
    <div className="space-y-6">
      <IpPageHeader
        eyebrow="Encrypted Vault & Sync Sources"
        title="Connections & Pull Sync Checkpoints"
        subtitle="Provision OAuth2, API Key, and Bearer connectors with pre-flight verification, SHA-256 duplicate fingerprinting, and stream checkpoints."
        actions={
          <Button type="button" size="sm" onClick={() => setCreateOpen(true)} className="gap-1.5">
            <Plus className="h-4 w-4" />
            <span>New Connection</span>
          </Button>
        }
      />

      <ApiProblemBanner
        problem={connectionsView.problem}
        onRetry={() => void connectionsView.refetch()}
      />

      <Tabs value={statusTab} onValueChange={setStatusTab}>
        <TabsList>
          <TabsTrigger value={ALL_TAB}>All</TabsTrigger>
          <TabsTrigger value={ConnectionStatus.ACTIVE}>Active</TabsTrigger>
          <TabsTrigger value={ConnectionStatus.AUTH_EXPIRED}>Auth Expired</TabsTrigger>
          <TabsTrigger value={ConnectionStatus.DISCONNECTED}>Disconnected</TabsTrigger>
          <TabsTrigger value={ConnectionStatus.DEACTIVATED}>Deactivated</TabsTrigger>
        </TabsList>
      </Tabs>

      <DataTable
        table={table}
        columnsLength={columns.length}
        isLoading={connectionsView.isLoading}
        dataLength={rows.length}
        ariaLabel="Tenant integration connections"
        emptyIcon={<Cable className="h-6 w-6" />}
        emptyTitle="No Connections Configured"
        emptyDescription="Click New Connection to launch the Connector Catalog and run a pre-flight check."
        onRowClick={(row) => navigation.toConnectionDetail(row.original.id)}
      />

      <CreateConnectionModal
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(id) => navigation.toConnectionDetail(id)}
      />
    </div>
  );
}
