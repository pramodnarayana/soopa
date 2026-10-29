import {
  type ApiProblem,
  Button,
  CopyableIdPill,
  Skeleton,
  StatusBadge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@soopa/ui';
import { ArrowLeft } from 'lucide-react';
import React, { useState } from 'react';
import { useConnectionDetailQuery } from '../../application/use-connection-queries';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { IpPageHeader } from '../shared/IpPageHeader';
import { mapConnectionStatusTone } from '../shared/status-mapping';
import {
  ConnectionCatalogTab,
  ConnectionOverviewTab,
  ConnectionStreamsSyncTab,
} from './ConnectionDetailTabs';

export interface IpConnectionDetailPageProps {
  readonly connectionId: string;
}

export function IpConnectionDetailPage({ connectionId }: IpConnectionDetailPageProps) {
  const { navigation } = useIpWorkspace();
  const [actionProblem, setActionProblem] = useState<ApiProblem | null>(null);
  const detailView = useConnectionDetailQuery(connectionId);
  const connection = detailView.data;

  return (
    <div className="space-y-6">
      <IpPageHeader
        eyebrow="Connector Control & Checkpoints"
        title={connection ? connection.name : `Connection ${connectionId}`}
        subtitle="Inspect schema catalogs, trigger incremental or full-refresh pull syncs, and rotate encrypted credentials without downtime."
        actions={
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => navigation.toConnections()}
            className="gap-1.5"
          >
            <ArrowLeft className="h-4 w-4" />
            <span>Connections</span>
          </Button>
        }
      />

      <ApiProblemBanner
        problem={actionProblem ?? detailView.problem}
        onRetry={() => void detailView.refetch()}
      />

      {detailView.isLoading || !connection ? (
        <Skeleton className="h-72 w-full rounded-xl" />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card px-4 py-3">
            <StatusBadge
              label={connection.status}
              tone={mapConnectionStatusTone(connection.status)}
            />
            <CopyableIdPill value={connection.id} prefixLabel="Connection ID" />
            <CopyableIdPill value={connection.appId} prefixLabel="Connector" />
          </div>

          <Tabs defaultValue="streams">
            <TabsList>
              <TabsTrigger value="streams">Checkpoints & Sync Runs</TabsTrigger>
              <TabsTrigger value="catalog">Schema Catalog</TabsTrigger>
              <TabsTrigger value="overview">Credentials & Lifecycle</TabsTrigger>
            </TabsList>

            <TabsContent value="streams" className="pt-4">
              <ConnectionStreamsSyncTab
                connectionId={connection.id}
                onOpenTrace={(traceId) => navigation.toTraceDetail(traceId)}
                onProblem={setActionProblem}
              />
            </TabsContent>

            <TabsContent value="catalog" className="pt-4">
              <ConnectionCatalogTab
                connectionId={connection.id}
                onProblem={setActionProblem}
                onConfigureTransformation={() => navigation.toTransformations(connection.id)}
              />
            </TabsContent>

            <TabsContent value="overview" className="pt-4">
              <ConnectionOverviewTab
                connection={connection}
                onProblem={setActionProblem}
                onDeactivated={() => void detailView.refetch()}
              />
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}
