import {
  Button,
  CopyableIdPill,
  Skeleton,
  SplitInspectorDrawer,
  StatusBadge,
  StatusTone,
} from '@soopa/ui';
import { Activity, ArrowLeft } from 'lucide-react';
import React, { useState } from 'react';
import { useStitchDefinitionQuery, useStitchRunQuery } from '../../application/use-stitch-queries';
import type { StitchDefinition, StitchRun, StitchStepRun } from '../../domain/stitch';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { IpPageHeader } from '../shared/IpPageHeader';
import { formatRelativeTimestamp, mapStitchRunStatusTone } from '../shared/status-mapping';
import { StitchDagCanvas } from './StitchDagCanvas';

export interface IpStitchRunPageProps {
  readonly runId: string;
}

function StepTelemetryDrawer({
  run,
  selectedStep,
  onSelectNode,
}: {
  readonly run: StitchRun;
  readonly selectedStep: StitchStepRun | undefined;
  readonly onSelectNode: (nodeKey: string) => void;
}) {
  return (
    <SplitInspectorDrawer
      title={selectedStep ? `Step: ${selectedStep.nodeKey}` : 'Step Execution Telemetry'}
      subtitle={
        selectedStep
          ? `Step Run ID: ${selectedStep.stepRunId}`
          : 'Click any DAG node or step below to inspect retry budgets.'
      }
    >
      <div className="space-y-4 text-xs">
        {selectedStep ? (
          <div className="space-y-3 rounded-xl border border-border bg-muted/30 p-4">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-foreground">Execution Status</span>
              <StatusBadge
                label={selectedStep.status}
                tone={mapStitchRunStatusTone(selectedStep.status)}
              />
            </div>

            <div className="grid grid-cols-2 gap-3 pt-1">
              <div className="rounded-lg border border-border bg-card p-2.5">
                <div className="text-muted-foreground">App Retries (User Budget)</div>
                <div className="mt-1 font-mono text-base font-bold tabular-nums">
                  {selectedStep.appRetryCount}
                </div>
              </div>
              <div className="rounded-lg border border-border bg-card p-2.5">
                <div className="text-muted-foreground">Internal 429/System Retries</div>
                <div className="mt-1 font-mono text-base font-bold text-brand-ink tabular-nums">
                  {selectedStep.internalRetryCount}
                </div>
              </div>
            </div>

            <p className="text-muted-foreground">
              Total Attempts: <span className="font-mono">{selectedStep.retryCount}</span> · Loop
              Iteration: <span className="font-mono">#{selectedStep.iterationCount}</span> · Created{' '}
              {formatRelativeTimestamp(selectedStep.createdAt)}
            </p>

            {selectedStep.failureDetail ? (
              <div className="rounded-lg border border-status-critical-border bg-status-critical-bg p-3 text-status-critical-fg">
                <div className="font-mono font-bold">
                  {selectedStep.failureCode ?? 'STEP_FAILURE'}
                </div>
                <div className="mt-1">{selectedStep.failureDetail}</div>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="space-y-1.5">
          <div className="font-semibold tracking-wider text-muted-foreground uppercase">
            All Step Runs ({run.steps.length})
          </div>
          {run.steps.map((step) => (
            <Button
              key={step.stepRunId}
              type="button"
              variant="outline"
              onClick={() => onSelectNode(step.nodeKey)}
              className="h-auto w-full justify-between px-3 py-2 text-left"
            >
              <div>
                <div className="font-mono text-xs font-semibold">{step.nodeKey}</div>
                <div className="font-mono text-xs text-muted-foreground">
                  app:{step.appRetryCount} · sys:{step.internalRetryCount}
                </div>
              </div>
              <StatusBadge label={step.status} tone={mapStitchRunStatusTone(step.status)} />
            </Button>
          ))}
        </div>
      </div>
    </SplitInspectorDrawer>
  );
}

function StitchRunBody({
  run,
  definition,
}: {
  readonly run: StitchRun;
  readonly definition: StitchDefinition | undefined;
}) {
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const defaultNodeKey = run.steps[0]?.nodeKey ?? null;
  const effectiveNodeKey = selectedNodeKey ?? defaultNodeKey;
  const selectedStep = run.steps.find((s) => s.nodeKey === effectiveNodeKey);

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card px-4 py-3">
        <StatusBadge label={run.status} tone={mapStitchRunStatusTone(run.status)} />
        <StatusBadge label={run.priority} tone={StatusTone.NEUTRAL} />
        <CopyableIdPill value={run.traceId} prefixLabel="Trace" />
        {run.correlationId ? (
          <CopyableIdPill value={run.correlationId} prefixLabel="Correlation" />
        ) : null}
        <CopyableIdPill value={run.idempotencyKey} prefixLabel="Idempotency" truncateLength={18} />
        {run.concurrencyKey ? (
          <CopyableIdPill value={run.concurrencyKey} prefixLabel="Concurrency Slot" />
        ) : null}
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <div className="xl:col-span-8">
          {definition ? (
            <StitchDagCanvas
              nodes={definition.nodes}
              stepRuns={run.steps}
              selectedNodeKey={effectiveNodeKey}
              onSelectNode={setSelectedNodeKey}
            />
          ) : (
            <Skeleton className="h-72 w-full rounded-2xl" />
          )}
        </div>

        <div className="xl:col-span-4">
          <StepTelemetryDrawer
            run={run}
            selectedStep={selectedStep}
            onSelectNode={setSelectedNodeKey}
          />
        </div>
      </div>
    </>
  );
}

export function IpStitchRunPage({ runId }: IpStitchRunPageProps) {
  const { navigation } = useIpWorkspace();
  const runView = useStitchRunQuery(runId);
  const run = runView.data;
  const defView = useStitchDefinitionQuery(run?.workflowId ?? '', run?.workflowVersion);
  const combinedProblem = runView.problem ?? defView.problem;

  return (
    <div className="space-y-6">
      <IpPageHeader
        eyebrow="Durable Stitch Run Inspector"
        title={`Stitch Run ${runId}`}
        subtitle="Live topological step state, concurrency slot isolation, and separated user vs. rate-limit retry budgets."
        actions={
          <div className="flex items-center gap-2">
            {run ? (
              <Button
                type="button"
                size="sm"
                onClick={() => navigation.toTraceDetail(run.traceId)}
                className="gap-1.5"
              >
                <Activity className="h-3.5 w-3.5" />
                <span>Open 5-Layer Trace</span>
              </Button>
            ) : null}
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
          </div>
        }
      />

      <ApiProblemBanner problem={combinedProblem} onRetry={() => void runView.refetch()} />

      {runView.isLoading || !run ? (
        <Skeleton className="h-80 w-full rounded-xl" />
      ) : (
        <StitchRunBody run={run} definition={defView.data} />
      )}
    </div>
  );
}
