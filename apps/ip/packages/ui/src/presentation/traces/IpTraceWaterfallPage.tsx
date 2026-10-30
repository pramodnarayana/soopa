import {
  type ApiProblem,
  Button,
  CopyableIdPill,
  LineageTree,
  type LineageTreeNode,
  ReplayBadge,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  StatusBadge,
} from '@soopa/ui';
import { ArrowLeft, Edit3, RotateCcw } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  useIpTraceLineageQuery,
  useIpTraceQuery,
  useReplayTransactionMutation,
} from '../../application/use-trace-queries';
import { PipelineLayer, type PipelineLayerValue, type ReplayStageValue } from '../../domain/enums';
import {
  computePipelineWaterfallSummary,
  deriveEligibleReplayStages,
} from '../../domain/replay/derive-replay-eligibility';
import type { IpTrace, IpTraceLineageItem } from '../../domain/trace';
import { isReplayStageValue } from '../../domain/type-guards';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { FiveLayerStageStrip } from '../shared/FiveLayerStagePill';
import { IpPageHeader } from '../shared/IpPageHeader';
import {
  formatLayerLabel,
  formatRelativeTimestamp,
  formatReplayStageLabel,
  mapTraceStatusTone,
} from '../shared/status-mapping';
import { ModifyAndReplayModal } from './ModifyAndReplayModal';
import { TraceWaterfallStageContent } from './TraceWaterfallStages';

export interface IpTraceWaterfallPageProps {
  readonly traceId: string;
}

function toLineageNodes(items: readonly IpTraceLineageItem[]): LineageTreeNode[] {
  return items.map((item) => ({
    id: item.traceId,
    parentId: item.parentTraceId,
    title: item.traceId,
    subtitle: `${formatLayerLabel(item.primaryLayer)} · ${formatRelativeTimestamp(item.createdAt)}`,
    statusLabel: item.status,
    statusTone: mapTraceStatusTone(item.status),
    replayCount: item.replayCount,
    timestamp: item.createdAt ?? undefined,
  }));
}

function ReplayActionControls({
  trace,
  onNavigateTrace,
  onOpenModifyStudio,
  onProblem,
}: {
  readonly trace: IpTrace;
  readonly onNavigateTrace: (traceId: string) => void;
  readonly onOpenModifyStudio: () => void;
  readonly onProblem: (problem: ApiProblem | null) => void;
}) {
  const eligibility = useMemo(() => deriveEligibleReplayStages(trace), [trace]);
  const [stageOverride, setStageOverride] = useState<ReplayStageValue | null>(null);
  const selectedStage = stageOverride ?? eligibility.recommendedStage ?? eligibility.stages[0];
  const replayMutation = useReplayTransactionMutation();

  if (!selectedStage) {
    return null;
  }

  const handleReplay = async (): Promise<void> => {
    onProblem(null);
    const res = await replayMutation.mutateAsync({
      traceId: trace.traceId,
      stage: selectedStage,
    });
    if (!res.ok) {
      onProblem(res.error);
      return;
    }
    toast.success(`Spawned child trace ${res.value.newTraceId}`);
    onNavigateTrace(res.value.newTraceId);
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="w-60">
        <Select
          value={selectedStage}
          onValueChange={(val) => {
            if (isReplayStageValue(val)) {
              setStageOverride(val);
            }
          }}
        >
          <SelectTrigger aria-label="Select deterministic replay stage" className="h-9 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {eligibility.stages.map((st) => (
              <SelectItem key={st} value={st}>
                {formatReplayStageLabel(st)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Button
        type="button"
        size="sm"
        disabled={replayMutation.isPending}
        onClick={() => void handleReplay()}
        className="gap-1.5"
      >
        <RotateCcw className="h-3.5 w-3.5" />
        <span>{replayMutation.isPending ? 'Replaying...' : 'Deterministic Replay'}</span>
      </Button>

      {eligibility.modifiableStages.length > 0 ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onOpenModifyStudio}
          className="gap-1.5"
        >
          <Edit3 className="h-3.5 w-3.5" />
          <span>Modify & Replay</span>
        </Button>
      ) : null}
    </div>
  );
}

function TraceWaterfallBody({
  trace,
  lineageItems,
  hydratePayloads,
  onHydrateS3,
  onProblem,
}: {
  readonly trace: IpTrace;
  readonly lineageItems: readonly IpTraceLineageItem[];
  readonly hydratePayloads: boolean;
  readonly onHydrateS3: () => void;
  readonly onProblem: (problem: ApiProblem | null) => void;
}) {
  const { navigation } = useIpWorkspace();
  const [activeLayer, setActiveLayer] = useState<PipelineLayerValue>(PipelineLayer.L1_INGEST);
  const [modifyOpen, setModifyOpen] = useState(false);

  const waterfallSummary = useMemo(() => computePipelineWaterfallSummary(trace), [trace]);
  const eligibility = useMemo(() => deriveEligibleReplayStages(trace), [trace]);
  const lineageNodes = useMemo(() => toLineageNodes(lineageItems), [lineageItems]);
  const hasLineage = lineageNodes.length > 0;

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge label={trace.status} tone={mapTraceStatusTone(trace.status)} />
          <ReplayBadge count={trace.replayCount} />
          <CopyableIdPill value={trace.traceId} prefixLabel="Trace" />
          {trace.correlationId ? (
            <CopyableIdPill value={trace.correlationId} prefixLabel="Correlation" />
          ) : null}
          <CopyableIdPill value={trace.originalTraceId} prefixLabel="Root" truncateLength={16} />
        </div>

        <ReplayActionControls
          trace={trace}
          onNavigateTrace={(nextId) => navigation.toTraceDetail(nextId)}
          onOpenModifyStudio={() => setModifyOpen(true)}
          onProblem={onProblem}
        />
      </div>

      <FiveLayerStageStrip
        layers={waterfallSummary.layers}
        activeLayer={activeLayer}
        onSelectLayer={setActiveLayer}
      />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        {hasLineage ? (
          <div className="xl:col-span-4">
            <LineageTree
              nodes={lineageNodes}
              activeNodeId={trace.traceId}
              onSelectNode={(nextId) => navigation.toTraceDetail(nextId)}
            />
          </div>
        ) : null}

        <div className={hasLineage ? 'xl:col-span-8' : 'xl:col-span-12'}>
          <TraceWaterfallStageContent
            activeLayer={activeLayer}
            trace={trace}
            hasUnhydratedS3={!hydratePayloads && waterfallSummary.hasUnhydratedS3Payloads}
            onHydrateS3={onHydrateS3}
            onOpenStitches={() => navigation.toStitches()}
          />
        </div>
      </div>

      <ModifyAndReplayModal
        open={modifyOpen}
        onOpenChange={setModifyOpen}
        trace={trace}
        modifiableStages={eligibility.modifiableStages}
        onReplayCreated={(newTraceId) => navigation.toTraceDetail(newTraceId)}
      />
    </>
  );
}

export function IpTraceWaterfallPage({ traceId }: IpTraceWaterfallPageProps) {
  const { navigation } = useIpWorkspace();
  const [hydratePayloads, setHydratePayloads] = useState(false);
  const [actionProblem, setActionProblem] = useState<ApiProblem | null>(null);

  const traceView = useIpTraceQuery(traceId, hydratePayloads);
  const lineageView = useIpTraceLineageQuery(traceId);
  const trace = traceView.data;
  const combinedProblem = actionProblem ?? traceView.problem ?? lineageView.problem;

  return (
    <div className="space-y-6">
      <IpPageHeader
        eyebrow="5-Layer Transaction Waterfall"
        title={`Trace ${traceId}`}
        subtitle="End-to-end cryptographic wire audit, universal replica state, canonical GEM bindings, and deterministic replay lineage."
        actions={
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => navigation.toTraces()}
            className="gap-1.5"
          >
            <ArrowLeft className="h-4 w-4" />
            <span>Timeline</span>
          </Button>
        }
      />

      <ApiProblemBanner problem={combinedProblem} onRetry={() => void traceView.refetch()} />

      {traceView.isLoading || !trace ? (
        <div className="space-y-4">
          <Skeleton className="h-24 w-full rounded-xl" />
          <Skeleton className="h-80 w-full rounded-xl" />
        </div>
      ) : (
        <TraceWaterfallBody
          trace={trace}
          lineageItems={lineageView.data ?? []}
          hydratePayloads={hydratePayloads}
          onHydrateS3={() => setHydratePayloads(true)}
          onProblem={setActionProblem}
        />
      )}
    </div>
  );
}
