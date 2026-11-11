import {
  type ApiProblem,
  Button,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@soopa/ui';
import { ArrowLeft } from 'lucide-react';
import React, { useState } from 'react';
import { useConnectionDetailQuery } from '../../application/use-connection-queries';
import { UNIVERSAL_SIMULATOR_APP_ID } from '../../domain/enums';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { SyncedDataInspectionPanel } from '../records/SyncedDataInspectionPanel';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { IpPageHeader } from '../shared/IpPageHeader';
import { ConnectionEntitiesSyncTab, ConnectionOverviewTab } from './ConnectionDetailTabs';
import { SimulatorEntitiesSection } from './SimulatorEntitiesSection';

export const ConnectionDetailTab = {
  CONNECTION: 'connection',
  ENTITIES: 'entities',
  DATA: 'data',
} as const;

export type ConnectionDetailTabValue =
  (typeof ConnectionDetailTab)[keyof typeof ConnectionDetailTab];

const DETAIL_TAB_TRIGGER_CLASS =
  'rounded-none border-b-2 border-transparent bg-transparent px-1 py-2.5 text-sm font-medium text-muted-foreground shadow-none hover:text-foreground data-[state=active]:border-primary data-[state=active]:text-foreground data-[state=active]:bg-transparent data-[state=active]:shadow-none -mb-px';

export interface IpConnectionDetailPageProps {
  readonly connectionId: string;
  readonly initialTab?: ConnectionDetailTabValue;
}

export function IpConnectionDetailPage({
  connectionId,
  initialTab = ConnectionDetailTab.CONNECTION,
}: IpConnectionDetailPageProps) {
  const { navigation } = useIpWorkspace();
  const [actionProblem, setActionProblem] = useState<ApiProblem | null>(null);
  const [activeTab, setActiveTab] = useState<string>(initialTab);
  const [inspectEntityFilter, setInspectEntityFilter] = useState<string | null>(null);

  const detailView = useConnectionDetailQuery(connectionId);
  const connection = detailView.data;
  const isSimulator = connection?.appId === UNIVERSAL_SIMULATOR_APP_ID;

  const handleInspectEntity = (entityName: string) => {
    setInspectEntityFilter(entityName);
    setActiveTab(ConnectionDetailTab.DATA);
  };

  return (
    <div className="space-y-6">
      <IpPageHeader
        title={connection ? connection.name : `Connection ${connectionId}`}
        actions={
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => navigation.toConnections()}
            className="gap-1.5"
          >
            <ArrowLeft className="h-4 w-4" />
            <span>Back</span>
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
        <Tabs
          value={activeTab}
          onValueChange={(nextTab) => {
            setActionProblem(null);
            setActiveTab(nextTab);
          }}
        >
          <TabsList className="w-full justify-start rounded-none border-b border-border bg-transparent p-0 h-auto gap-8">
            <TabsTrigger
              value={ConnectionDetailTab.CONNECTION}
              className={DETAIL_TAB_TRIGGER_CLASS}
            >
              Connection
            </TabsTrigger>
            <TabsTrigger value={ConnectionDetailTab.ENTITIES} className={DETAIL_TAB_TRIGGER_CLASS}>
              Entities
            </TabsTrigger>
            <TabsTrigger value={ConnectionDetailTab.DATA} className={DETAIL_TAB_TRIGGER_CLASS}>
              Data
            </TabsTrigger>
          </TabsList>

          <TabsContent value={ConnectionDetailTab.CONNECTION} className="space-y-6 pt-4">
            <ConnectionOverviewTab
              connection={connection}
              onProblem={setActionProblem}
              onDeactivated={() => navigation.toConnections()}
              onDeleted={() => navigation.toConnections()}
            />
            {isSimulator ? (
              <SimulatorEntitiesSection connectionId={connection.id} onProblem={setActionProblem} />
            ) : null}
          </TabsContent>

          <TabsContent value={ConnectionDetailTab.ENTITIES} className="pt-4">
            <ConnectionEntitiesSyncTab
              connectionId={connection.id}
              connection={connection}
              onInspectEntity={handleInspectEntity}
              onOpenTrace={(traceId) => navigation.toTraceDetail(traceId)}
              onProblem={setActionProblem}
            />
          </TabsContent>

          <TabsContent value={ConnectionDetailTab.DATA} className="pt-4">
            <SyncedDataInspectionPanel
              connectionId={connection.id}
              initialEntityFilter={inspectEntityFilter}
              onOpenTrace={(traceId) => navigation.toTraceDetail(traceId)}
            />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
