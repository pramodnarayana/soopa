import {
  type ApiProblem,
  Button,
  CopyableIdPill,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  MonacoCodeViewer,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from '@soopa/ui';
import React, { useState } from 'react';
import { toast } from 'sonner';
import {
  useDispatchStitchEventMutation,
  useRegisterStitchMutation,
} from '../../application/use-stitch-queries';
import { parseJsonObject } from '../../domain/replay/parse-json-object';
import type { StitchDefinition, TriggerStitchEventResult } from '../../domain/stitch';
import { buildRegisterStitchInput } from '../../domain/stitch-registration';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';

export function RegisterStitchModal({
  open,
  onOpenChange,
  definitions,
}: {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly definitions: readonly StitchDefinition[];
}) {
  const firstDef = definitions[0];
  const [workflowId, setWorkflowId] = useState(firstDef?.workflowId ?? '');
  const [canonicalEventType, setCanonicalEventType] = useState('energy.mdm_meter_reading');
  const [idempotencyField, setIdempotencyField] = useState('source_id');
  const [concurrencyField, setConcurrencyField] = useState('source_id');
  const [isTrigger, setIsTrigger] = useState(true);
  const [conditionKey, setConditionKey] = useState('');
  const [problem, setProblem] = useState<ApiProblem | null>(null);

  const registerMutation = useRegisterStitchMutation();
  const effectiveWorkflowId = workflowId || firstDef?.workflowId || '';
  const matchedDef = definitions.find((d) => d.workflowId === effectiveWorkflowId);

  const handleRegister = async (): Promise<void> => {
    const input = buildRegisterStitchInput({
      workflowId: effectiveWorkflowId,
      workflowVersion: matchedDef?.version ?? 1,
      canonicalEventType,
      isTrigger,
      conditionKey,
      idempotencyField,
      concurrencyField,
    });
    if (!input) {
      return;
    }
    setProblem(null);
    const res = await registerMutation.mutateAsync(input);
    if (!res.ok) {
      setProblem(res.error);
      return;
    }
    toast.success(`Registered Stitch ${res.value.id} on ${res.value.workflowId}.`);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Register L4 Stitch</DialogTitle>
          <DialogDescription>
            Bind an L3 Canonical Event Type to start a durable Stitch workflow DAG or satisfy a
            WAIT_FOR_EVENT gate.
          </DialogDescription>
        </DialogHeader>

        <ApiProblemBanner problem={problem} />

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>Workflow DAG Definition</Label>
            <Select value={effectiveWorkflowId} onValueChange={setWorkflowId}>
              <SelectTrigger aria-label="Select workflow DAG">
                <SelectValue placeholder="Choose workflow definition" />
              </SelectTrigger>
              <SelectContent>
                {definitions.map((def) => (
                  <SelectItem key={def.workflowId} value={def.workflowId}>
                    {def.workflowId} (v{def.version})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="stitch-canonical-type">Canonical Event Type</Label>
            <Input
              id="stitch-canonical-type"
              value={canonicalEventType}
              onChange={(e) => setCanonicalEventType(e.target.value)}
              className="font-mono text-sm"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="stitch-idem-field">Idempotency Key Field</Label>
              <Input
                id="stitch-idem-field"
                value={idempotencyField}
                onChange={(e) => setIdempotencyField(e.target.value)}
                className="font-mono text-xs"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="stitch-conc-field">Concurrency Key Field</Label>
              <Input
                id="stitch-conc-field"
                value={concurrencyField}
                onChange={(e) => setConcurrencyField(e.target.value)}
                className="font-mono text-xs"
              />
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <Switch id="stitch-is-trigger" checked={isTrigger} onCheckedChange={setIsTrigger} />
            <Label htmlFor="stitch-is-trigger" className="text-xs">
              {isTrigger ? 'Trigger New Stitch Run' : 'Signal Existing WAIT_FOR_EVENT Gate'}
            </Label>
          </div>

          {!isTrigger ? (
            <div className="space-y-1.5">
              <Label htmlFor="stitch-cond-key">Wait Condition Event Key</Label>
              <Input
                id="stitch-cond-key"
                value={conditionKey}
                onChange={(e) => setConditionKey(e.target.value)}
                className="font-mono text-xs"
              />
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={registerMutation.isPending || !effectiveWorkflowId}
            onClick={() => void handleRegister()}
          >
            {registerMutation.isPending ? 'Registering...' : 'Register Stitch'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const DEFAULT_EVENT_PAYLOAD = JSON.stringify(
  {
    source_id: 'MTR-700',
    kwh_delivered: '142.85',
  },
  null,
  2,
);

export function DispatchCanonicalEventModal({
  open,
  onOpenChange,
  onOpenRun,
}: {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly onOpenRun: (runId: string) => void;
}) {
  const [canonicalEventType, setCanonicalEventType] = useState('energy.mdm_meter_reading');
  const [correlationId, setCorrelationId] = useState('MTR-700');
  const [payloadText, setPayloadText] = useState(DEFAULT_EVENT_PAYLOAD);
  const [result, setResult] = useState<TriggerStitchEventResult | null>(null);
  const [problem, setProblem] = useState<ApiProblem | null>(null);

  const dispatchMutation = useDispatchStitchEventMutation();
  const parsedCandidate = parseJsonObject(payloadText);

  const handleDispatch = async (): Promise<void> => {
    if (!parsedCandidate.ok || !canonicalEventType.trim()) {
      return;
    }
    setProblem(null);
    const res = await dispatchMutation.mutateAsync({
      canonicalEventType: canonicalEventType.trim(),
      correlationId: correlationId.trim() || null,
      payload: parsedCandidate.value,
    });
    if (!res.ok) {
      setProblem(res.error);
      return;
    }
    setResult(res.value);
    toast.success(`Dispatched canonical event (${res.value.startedRunIds.length} run(s) started).`);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Test Canonical Event Dispatcher</DialogTitle>
          <DialogDescription>
            Emit a synthetic L3 canonical event to verify Stitch fan-out, idempotency deduplication,
            or WAIT_FOR_EVENT gate signalling.
          </DialogDescription>
        </DialogHeader>

        <ApiProblemBanner problem={problem} />

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="disp-evt-type">Canonical Event Type</Label>
              <Input
                id="disp-evt-type"
                value={canonicalEventType}
                onChange={(e) => setCanonicalEventType(e.target.value)}
                className="font-mono text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="disp-corr-id">Correlation ID</Label>
              <Input
                id="disp-corr-id"
                value={correlationId}
                onChange={(e) => setCorrelationId(e.target.value)}
                className="font-mono text-xs"
              />
            </div>
          </div>

          <MonacoCodeViewer
            height={200}
            readOnly={false}
            value={payloadText}
            onChange={setPayloadText}
          />

          {result ? (
            <div className="space-y-2 rounded-xl border border-border bg-accent/50 p-3 text-xs">
              <div>
                <strong>Started Runs ({result.startedRunIds.length}):</strong>{' '}
                {result.startedRunIds.map((id) => (
                  <Button
                    key={id}
                    type="button"
                    variant="link"
                    size="sm"
                    onClick={() => {
                      onOpenChange(false);
                      onOpenRun(id);
                    }}
                    className="h-auto p-0 font-mono text-xs"
                  >
                    {id}
                  </Button>
                ))}
              </div>
              <div className="flex flex-wrap gap-2">
                {result.deduplicatedRunIds.map((id) => (
                  <CopyableIdPill key={id} value={id} prefixLabel="Deduplicated" />
                ))}
                {result.signalledStepIds.map((id) => (
                  <CopyableIdPill key={id} value={id} prefixLabel="Signalled Step" />
                ))}
              </div>
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button
            type="button"
            disabled={!parsedCandidate.ok || dispatchMutation.isPending}
            onClick={() => void handleDispatch()}
          >
            {dispatchMutation.isPending ? 'Dispatching...' : 'Dispatch Event'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
