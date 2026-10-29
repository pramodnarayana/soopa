import {
  type ApiProblem,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
  MonacoJsonDiffViewer,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@soopa/ui';
import React, { useEffect, useState } from 'react';
import { useModifyAndReplayMutation } from '../../application/use-trace-queries';
import { isReplayStageValue, ReplayStage, type ReplayStageValue } from '../../domain/enums';
import { extractModifiablePayloadSeed } from '../../domain/replay/derive-replay-eligibility';
import { parseJsonObject } from '../../domain/replay/parse-json-object';
import type { IpTrace } from '../../domain/trace';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { formatReplayStageLabel, stringifyJsonPretty } from '../shared/status-mapping';

export interface ModifyAndReplayModalProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly trace: IpTrace;
  readonly modifiableStages: readonly ReplayStageValue[];
  readonly onReplayCreated: (newTraceId: string) => void;
}

export function ModifyAndReplayModal({
  open,
  onOpenChange,
  trace,
  modifiableStages,
  onReplayCreated,
}: ModifyAndReplayModalProps) {
  const defaultStage = modifiableStages[0] ?? ReplayStage.RETRY_INGEST;
  const [selectedStage, setSelectedStage] = useState<ReplayStageValue>(defaultStage);
  const seedJson = stringifyJsonPretty(extractModifiablePayloadSeed(trace, selectedStage));
  const [modifiedText, setModifiedText] = useState<string>(seedJson);
  const [problem, setProblem] = useState<ApiProblem | null>(null);
  const mutation = useModifyAndReplayMutation();

  useEffect(() => {
    setModifiedText(stringifyJsonPretty(extractModifiablePayloadSeed(trace, selectedStage)));
  }, [trace, selectedStage]);

  const parsedCandidate = parseJsonObject(modifiedText);

  const handleExecute = async (): Promise<void> => {
    if (!parsedCandidate.ok) {
      return;
    }
    setProblem(null);
    const res = await mutation.mutateAsync({
      traceId: trace.traceId,
      stage: selectedStage,
      modifiedPayload: parsedCandidate.value,
    });
    if (!res.ok) {
      setProblem(res.error);
      return;
    }
    onOpenChange(false);
    onReplayCreated(res.value.newTraceId);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>Modify & Replay Studio</DialogTitle>
          <DialogDescription>
            Patch a malformed L1 ingress or L3 canonical payload side-by-side without mutating
            immutable historical records. A child trace linked via parent_trace_id will be created.
          </DialogDescription>
        </DialogHeader>

        <ApiProblemBanner problem={problem} />

        <div className="space-y-4">
          <div className="max-w-md space-y-1.5">
            <Label>Injection Stage</Label>
            <Select
              value={selectedStage}
              onValueChange={(val) => {
                if (isReplayStageValue(val)) {
                  setSelectedStage(val);
                }
              }}
            >
              <SelectTrigger aria-label="Select modify and replay stage">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {modifiableStages.map((stage) => (
                  <SelectItem key={stage} value={stage}>
                    {formatReplayStageLabel(stage)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <MonacoJsonDiffViewer
            height={380}
            originalValue={seedJson}
            modifiedValue={modifiedText}
            readOnlyModified={false}
            onModifiedChange={setModifiedText}
          />

          {!parsedCandidate.ok ? (
            <div className="rounded-lg border border-status-critical-border bg-status-critical-bg px-3 py-2 font-mono text-xs text-status-critical-fg">
              JSON Error: {parsedCandidate.reason}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={!parsedCandidate.ok || mutation.isPending}
            onClick={() => void handleExecute()}
          >
            {mutation.isPending ? 'Creating Child Trace...' : 'Commit Patch & Replay'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
