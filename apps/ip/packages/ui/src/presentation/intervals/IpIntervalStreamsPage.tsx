import { type ApiProblem, Button, Input } from '@soopa/ui';
import { RefreshCw } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { useConnectionsQuery } from '../../application/use-connection-queries';
import {
  useDailyCompletenessQuery,
  useDailyTouRollupsQuery,
  useDeviceIntervalLineageQuery,
  useIntervalReconciliationQuery,
  useRecordSettlementReceiptMutation,
} from '../../application/use-interval-queries';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { IpPageHeader } from '../shared/IpPageHeader';
import { DailyCompletenessRibbonPanel } from './DailyCompletenessRibbonPanel';
import { DailyTouBillingRollupsTable } from './DailyTouBillingRollupsTable';
import { DeviceLoadCurveLineageDrawer } from './DeviceLoadCurveLineageDrawer';
import { ZeroLossReconciliationBanner } from './ZeroLossReconciliationBanner';

export interface IpIntervalStreamsPageProps {
  readonly initialConnectionId?: string;
  readonly initialServiceDate?: string;
}

function resolveDefaultServiceDate(): string {
  return new Date().toISOString().slice(0, 10);
}

export function IpIntervalStreamsPage({
  initialConnectionId,
  initialServiceDate,
}: IpIntervalStreamsPageProps) {
  const { navigation } = useIpWorkspace();
  const connectionsView = useConnectionsQuery();
  const connections = connectionsView.data ?? [];

  const [selectedConnectionId, setSelectedConnectionId] = useState<string>(
    initialConnectionId ?? '',
  );
  const effectiveConnectionId = selectedConnectionId || connections[0]?.id || '';

  const [serviceDate, setServiceDate] = useState<string>(
    () => initialServiceDate ?? resolveDefaultServiceDate(),
  );
  const [selectedFeederId, setSelectedFeederId] = useState<string | null>(null);
  const [searchDeviceId, setSearchDeviceId] = useState<string>('');
  const [inspectedDeviceId, setInspectedDeviceId] = useState<string | null>(null);
  const [receiptProblem, setReceiptProblem] = useState<ApiProblem | null>(null);

  const reconciliationView = useIntervalReconciliationQuery({
    connectionId: effectiveConnectionId || undefined,
    recentLimit: 20,
  });

  const completenessView = useDailyCompletenessQuery(
    {
      connectionId: effectiveConnectionId,
      serviceDate,
    },
    Boolean(effectiveConnectionId),
  );

  const touRollupsView = useDailyTouRollupsQuery(
    {
      serviceDate,
      connectionId: effectiveConnectionId || undefined,
      feederId: selectedFeederId ?? undefined,
    },
    Boolean(serviceDate),
  );

  const filteredRollups = useMemo(() => {
    const raw = touRollupsView.data ?? [];
    return raw.filter((r) => {
      if (effectiveConnectionId && r.connectionId && r.connectionId !== effectiveConnectionId) {
        return false;
      }
      if (selectedFeederId && r.feederId !== selectedFeederId) {
        return false;
      }
      return true;
    });
  }, [touRollupsView.data, effectiveConnectionId, selectedFeederId]);

  const lineageView = useDeviceIntervalLineageQuery(inspectedDeviceId, serviceDate);
  const recordReceiptMutation = useRecordSettlementReceiptMutation();

  const firstProblem =
    connectionsView.problem ??
    reconciliationView.problem ??
    completenessView.problem ??
    touRollupsView.problem ??
    lineageView.problem;

  const handleRetryProblem = (): void => {
    if (connectionsView.problem) {
      void connectionsView.refetch();
    } else if (reconciliationView.problem) {
      void reconciliationView.refetch();
    } else if (completenessView.problem) {
      void completenessView.refetch();
    } else if (touRollupsView.problem) {
      void touRollupsView.refetch();
    } else if (lineageView.problem) {
      void lineageView.refetch();
    }
  };

  const handleRefreshAll = (): void => {
    void reconciliationView.refetch();
    if (effectiveConnectionId && serviceDate) {
      void completenessView.refetch();
    }
    if (serviceDate) {
      void touRollupsView.refetch();
    }
  };

  return (
    <div className="space-y-6">
      <IpPageHeader
        eyebrow="Columnar Batch Data Plane"
        title="High-Frequency Interval Streams"
        subtitle="Zero-Missing-Data batch reconciliation, 96-slot daily feeder completeness, Time-of-Use (TOU) settlement rollups, and two-tier L1–L5 Parquet lineage."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {connections.length > 0 ? (
              <select
                aria-label="Select interval connection"
                value={effectiveConnectionId}
                onChange={(e) => setSelectedConnectionId(e.target.value)}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
              >
                {connections.map((conn) => (
                  <option key={conn.id} value={conn.id}>
                    {conn.name} ({conn.appId})
                  </option>
                ))}
              </select>
            ) : null}
            <Input
              type="date"
              aria-label="Service date"
              value={serviceDate}
              onChange={(e) => setServiceDate(e.target.value)}
              className="w-40 font-mono text-xs"
            />
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              aria-label="Refresh interval metrics"
              onClick={handleRefreshAll}
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          </div>
        }
      />

      <ApiProblemBanner problem={firstProblem} onRetry={handleRetryProblem} />

      <ZeroLossReconciliationBanner
        overview={reconciliationView.data}
        isLoading={reconciliationView.isLoading}
        onInspectTrace={(traceId) => navigation.toTraceDetail(traceId)}
      />

      <DailyCompletenessRibbonPanel
        items={completenessView.data ?? []}
        selectedFeederId={selectedFeederId}
        onSelectFeeder={setSelectedFeederId}
        serviceDate={serviceDate}
      />

      <DailyTouBillingRollupsTable
        rollups={filteredRollups}
        isLoading={touRollupsView.isLoading}
        selectedFeederId={selectedFeederId}
        searchDeviceId={searchDeviceId}
        onSearchDeviceIdChange={setSearchDeviceId}
        onInspectDeviceCurve={(deviceId) => setInspectedDeviceId(deviceId)}
        onRecordSettlementReceipt={async (batchId, receiptId): Promise<boolean> => {
          setReceiptProblem(null);
          try {
            const res = await recordReceiptMutation.mutateAsync({
              batchId,
              deliveryReceiptId: receiptId,
            });
            if (res.ok) {
              return true;
            }
            setReceiptProblem(res.error);
            return false;
          } catch (err) {
            setReceiptProblem({
              status: 500,
              code: 'SERVER_ERROR',
              message: err instanceof Error ? err.message : 'Failed to record settlement receipt.',
            });
            return false;
          }
        }}
        isRecordingReceipt={recordReceiptMutation.isPending}
        receiptProblem={receiptProblem}
      />

      <DeviceLoadCurveLineageDrawer
        open={Boolean(inspectedDeviceId)}
        onOpenChange={(open) => {
          if (!open) {
            setInspectedDeviceId(null);
          }
        }}
        trace={lineageView.data}
        isLoading={lineageView.isLoading}
        onOpenBatchTrace={(traceId) => {
          setInspectedDeviceId(null);
          navigation.toTraceDetail(traceId);
        }}
      />
    </div>
  );
}
