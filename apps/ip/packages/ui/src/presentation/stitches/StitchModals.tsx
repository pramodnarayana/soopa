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
  MonacoCodeEditor,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Textarea,
} from '@soopa/ui';
import { AlertTriangle, Trash2 } from 'lucide-react';
import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { useMappingSpecsQuery } from '../../application/use-mapping-spec-queries';
import {
  useDeleteStitchMutation,
  useDispatchStitchEventMutation,
  useRegisterStitchMutation,
  useUpdateStitchMutation,
} from '../../application/use-stitch-queries';
import { parseJsonObject } from '../../domain/replay/parse-json-object';
import type { Stitch, StitchDefinition, TriggerStitchEventResult } from '../../domain/stitch';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';

const DEFAULT_EVENT_PAYLOAD = JSON.stringify(
  {
    source_id: 'rec_1001',
    status: 'ACTIVE',
  },
  null,
  2,
);

const NO_MAPPING_SPEC_VALUE = '__none__';

export function RegisterStitchModal({
  open,
  onOpenChange,
  definitions,
  onSuccess,
}: {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly definitions: readonly StitchDefinition[];
  readonly onSuccess?: (stitch: Stitch) => void;
}) {
  const firstDef = definitions[0];
  const [workflowId, setWorkflowId] = useState(firstDef?.workflowId ?? '');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [canonicalEventType, setCanonicalEventType] = useState('canonical.record.v1');
  const [mappingSpecId, setMappingSpecId] = useState<string>(NO_MAPPING_SPEC_VALUE);
  const [idempotencyField, setIdempotencyField] = useState('id');
  const [concurrencyField, setConcurrencyField] = useState('');
  const [isTrigger, setIsTrigger] = useState(true);
  const [conditionKey, setConditionKey] = useState('');
  const [isActive, setIsActive] = useState(true);
  const [problem, setProblem] = useState<ApiProblem | null>(null);

  const registerMutation = useRegisterStitchMutation();
  const mappingSpecsView = useMappingSpecsQuery();
  const mappingSpecs = mappingSpecsView.data ?? [];

  useEffect(() => {
    if (open) {
      setWorkflowId(firstDef?.workflowId ?? '');
      setName('');
      setDescription('');
      setCanonicalEventType('canonical.record.v1');
      setMappingSpecId(NO_MAPPING_SPEC_VALUE);
      setIdempotencyField('id');
      setConcurrencyField('');
      setIsTrigger(true);
      setConditionKey('');
      setIsActive(true);
      setProblem(null);
    }
  }, [open, firstDef?.workflowId]);

  const effectiveWorkflowId = workflowId || firstDef?.workflowId || '';
  const matchedDef = definitions.find((d) => d.workflowId === effectiveWorkflowId);

  const handleRegister = async (): Promise<void> => {
    if (!effectiveWorkflowId || !canonicalEventType.trim()) {
      return;
    }
    setProblem(null);
    const res = await registerMutation.mutateAsync({
      workflowId: effectiveWorkflowId,
      workflowVersion: matchedDef?.version ?? 1,
      name: name.trim(),
      description: description.trim(),
      mappingSpecId: mappingSpecId !== NO_MAPPING_SPEC_VALUE ? mappingSpecId : null,
      canonicalEventType: canonicalEventType.trim(),
      isTrigger,
      conditionEventKey: isTrigger ? null : conditionKey.trim() || null,
      idempotencyKeyField: idempotencyField.trim() || 'id',
      concurrencyKeyField: concurrencyField.trim() || null,
      isActive,
    });

    if (!res.ok) {
      setProblem(res.error);
      return;
    }

    toast.success(`Registered Stitch pipeline '${res.value.name || res.value.id}'.`);
    onOpenChange(false);
    if (onSuccess) {
      onSuccess(res.value);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Register Stitch Pipeline</DialogTitle>
          <DialogDescription>
            Bind an L3 Canonical Event Type to an executable Stitch DAG, optionally pairing it with
            a Field Mapping Spec for outbound wire formatting.
          </DialogDescription>
        </DialogHeader>

        <ApiProblemBanner problem={problem} />

        <div className="space-y-4 text-xs">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="register-name">Pipeline Name</Label>
              <Input
                id="register-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Outbound Device Reading Sync"
                className="text-xs"
              />
            </div>

            <div className="space-y-1">
              <Label>Workflow DAG Definition</Label>
              <Select value={effectiveWorkflowId} onValueChange={setWorkflowId}>
                <SelectTrigger aria-label="Select workflow definition" className="text-xs">
                  <SelectValue placeholder="Choose workflow definition" />
                </SelectTrigger>
                <SelectContent>
                  {definitions.map((def) => (
                    <SelectItem key={def.workflowId} value={def.workflowId} className="text-xs">
                      {def.workflowId} (v{def.version})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="register-description">Description</Label>
            <Textarea
              id="register-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Operational purpose, SLA, and target systems..."
              className="text-xs resize-none"
              rows={2}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="register-canonical-type">L3 Canonical Event Type</Label>
              <Input
                id="register-canonical-type"
                value={canonicalEventType}
                onChange={(e) => setCanonicalEventType(e.target.value)}
                placeholder="e.g. telemetry.device_reading"
                className="font-mono text-xs"
              />
            </div>

            <div className="space-y-1">
              <Label>Associated Field Mapping Spec</Label>
              <Select value={mappingSpecId} onValueChange={setMappingSpecId}>
                <SelectTrigger aria-label="Select mapping specification" className="text-xs">
                  <SelectValue placeholder="None (direct canonical projection)" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_MAPPING_SPEC_VALUE} className="text-xs">
                    None (Direct Canonical Pass-Through)
                  </SelectItem>
                  {mappingSpecs.map((spec) => (
                    <SelectItem key={spec.id} value={spec.id} className="text-xs">
                      {spec.name} ({spec.targetEntityName})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="register-idempotency-field">Idempotency Key Field</Label>
              <Input
                id="register-idempotency-field"
                value={idempotencyField}
                onChange={(e) => setIdempotencyField(e.target.value)}
                placeholder="id"
                className="font-mono text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="register-concurrency-field">Concurrency Key Field (Optional)</Label>
              <Input
                id="register-concurrency-field"
                value={concurrencyField}
                onChange={(e) => setConcurrencyField(e.target.value)}
                placeholder="e.g. device_id"
                className="font-mono text-xs"
              />
            </div>
          </div>

          <div className="rounded-md border border-border p-3 space-y-3 bg-muted/20">
            <div className="flex items-center justify-between">
              <div>
                <Label
                  htmlFor="register-is-trigger"
                  className="font-semibold text-xs cursor-pointer"
                >
                  DAG Root Trigger
                </Label>
                <p className="text-[11px] text-muted-foreground">
                  Starts a new workflow DAG instance upon receiving this canonical event.
                </p>
              </div>
              <Switch id="register-is-trigger" checked={isTrigger} onCheckedChange={setIsTrigger} />
            </div>

            {!isTrigger ? (
              <div className="space-y-1 pt-1 border-t border-border/50">
                <Label htmlFor="register-condition-key">Gate Condition Key</Label>
                <Input
                  id="register-condition-key"
                  value={conditionKey}
                  onChange={(e) => setConditionKey(e.target.value)}
                  placeholder="e.g. WAIT_FOR_PAYMENT"
                  className="font-mono text-xs"
                />
              </div>
            ) : null}

            <div className="flex items-center justify-between pt-1 border-t border-border/50">
              <div>
                <Label
                  htmlFor="register-is-active"
                  className="font-semibold text-xs cursor-pointer"
                >
                  Initial Pipeline State
                </Label>
                <p className="text-[11px] text-muted-foreground">
                  {isActive
                    ? 'Active and processing inbound events'
                    : 'Paused (events will not trigger runs)'}
                </p>
              </div>
              <Switch id="register-is-active" checked={isActive} onCheckedChange={setIsActive} />
            </div>
          </div>
        </div>

        <DialogFooter className="pt-2">
          <Button type="button" variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={
              registerMutation.isPending || !effectiveWorkflowId || !canonicalEventType.trim()
            }
            onClick={() => void handleRegister()}
          >
            {registerMutation.isPending ? 'Registering...' : 'Register Stitch'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function EditStitchModal({
  open,
  onOpenChange,
  stitch,
}: {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly stitch: Stitch | null;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [mappingSpecId, setMappingSpecId] = useState<string>(NO_MAPPING_SPEC_VALUE);
  const [isActive, setIsActive] = useState(true);
  const [problem, setProblem] = useState<ApiProblem | null>(null);

  const updateMutation = useUpdateStitchMutation();
  const mappingSpecsView = useMappingSpecsQuery();
  const mappingSpecs = mappingSpecsView.data ?? [];

  useEffect(() => {
    if (stitch) {
      setName(stitch.name ?? '');
      setDescription(stitch.description ?? '');
      setMappingSpecId(stitch.mappingSpecId ?? NO_MAPPING_SPEC_VALUE);
      setIsActive(stitch.isActive);
      setProblem(null);
    }
  }, [stitch, open]);

  if (!stitch) {
    return null;
  }

  const handleUpdate = async (): Promise<void> => {
    setProblem(null);
    const res = await updateMutation.mutateAsync({
      stitchId: stitch.id,
      input: {
        name: name.trim(),
        description: description.trim(),
        mappingSpecId: mappingSpecId !== NO_MAPPING_SPEC_VALUE ? mappingSpecId : null,
        isActive,
      },
    });

    if (!res.ok) {
      setProblem(res.error);
      return;
    }

    toast.success(`Updated Stitch pipeline '${res.value.name || res.value.id}'.`);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit Stitch Pipeline</DialogTitle>
          <DialogDescription>
            Update metadata, target Field Mapping Spec, and operational dispatch state.
          </DialogDescription>
        </DialogHeader>

        <ApiProblemBanner problem={problem} />

        <div className="space-y-4 text-xs">
          <div className="grid grid-cols-2 gap-3 p-2.5 rounded bg-muted/40 border border-border">
            <div>
              <span className="text-muted-foreground block text-[11px]">Stitch ID</span>
              <CopyableIdPill value={stitch.id} />
            </div>
            <div>
              <span className="text-muted-foreground block text-[11px]">Target Workflow DAG</span>
              <span className="font-mono font-semibold text-foreground">
                {stitch.workflowId} (v{stitch.workflowVersion})
              </span>
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="edit-name">Pipeline Name</Label>
            <Input
              id="edit-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Energy MDM Kafka Egress"
              className="text-xs"
            />
          </div>

          <div className="space-y-1">
            <Label htmlFor="edit-description">Description</Label>
            <Textarea
              id="edit-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Operational purpose, SLA, and routing notes..."
              className="text-xs resize-none"
              rows={2}
            />
          </div>

          <div className="space-y-1">
            <Label>Associated Field Mapping Spec</Label>
            <Select value={mappingSpecId} onValueChange={setMappingSpecId}>
              <SelectTrigger aria-label="Select mapping specification" className="text-xs">
                <SelectValue placeholder="None (Direct canonical pass-through)" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_MAPPING_SPEC_VALUE} className="text-xs">
                  None (Direct Canonical Pass-Through)
                </SelectItem>
                {mappingSpecs.map((spec) => (
                  <SelectItem key={spec.id} value={spec.id} className="text-xs">
                    {spec.name} ({spec.targetEntityName})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center justify-between p-3 rounded-md border border-border bg-muted/20">
            <div>
              <Label htmlFor="edit-is-active" className="font-semibold text-xs cursor-pointer">
                Pipeline Dispatch State
              </Label>
              <p className="text-[11px] text-muted-foreground">
                {isActive
                  ? 'ACTIVE · Receiving and triggering DAG runs'
                  : 'PAUSED · Incoming events ignored'}
              </p>
            </div>
            <Switch id="edit-is-active" checked={isActive} onCheckedChange={setIsActive} />
          </div>
        </div>

        <DialogFooter className="pt-2">
          <Button type="button" variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={updateMutation.isPending}
            onClick={() => void handleUpdate()}
          >
            {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function DeleteStitchModal({
  open,
  onOpenChange,
  stitch,
}: {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly stitch: Stitch | null;
}) {
  const [problem, setProblem] = useState<ApiProblem | null>(null);
  const deleteMutation = useDeleteStitchMutation();

  useEffect(() => {
    if (open) {
      setProblem(null);
    }
  }, [open]);

  if (!stitch) {
    return null;
  }

  const handleDelete = async (): Promise<void> => {
    setProblem(null);
    const res = await deleteMutation.mutateAsync(stitch.id);
    if (!res.ok) {
      setProblem(res.error);
      return;
    }
    toast.success(`Deleted Stitch pipeline '${stitch.name || stitch.id}'.`);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="h-5 w-5" />
            <DialogTitle>Delete Stitch Pipeline</DialogTitle>
          </div>
          <DialogDescription>
            Permanently remove this Stitch configuration from the Control Plane and unregister it
            from live event dispatching.
          </DialogDescription>
        </DialogHeader>

        <ApiProblemBanner problem={problem} />

        <div className="space-y-3 text-xs">
          <div className="rounded-md border border-destructive/20 bg-destructive/10 p-3 space-y-1 text-foreground">
            <p className="font-semibold text-xs">
              Are you sure you want to delete &ldquo;{stitch.name || stitch.workflowId}&rdquo;?
            </p>
            <p className="text-[11px] text-muted-foreground">
              Stitch ID: <span className="font-mono">{stitch.id}</span> · L3 Event:{' '}
              <span className="font-mono">{stitch.canonicalEventType}</span>
            </p>
          </div>

          <p className="text-muted-foreground text-xs leading-relaxed">
            Existing running instances of this DAG will complete execution, but any future events of
            type{' '}
            <code className="font-mono bg-muted px-1 py-0.5 rounded">
              {stitch.canonicalEventType}
            </code>{' '}
            will no longer trigger this pipeline.
          </p>
        </div>

        <DialogFooter className="pt-2">
          <Button type="button" variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            disabled={deleteMutation.isPending}
            onClick={() => void handleDelete()}
            className="gap-1.5"
          >
            <Trash2 className="h-3.5 w-3.5" />
            <span>{deleteMutation.isPending ? 'Deleting...' : 'Delete Pipeline'}</span>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function DispatchCanonicalEventModal({
  open,
  onOpenChange,
  onOpenRun,
  defaultCanonicalEventType,
}: {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly onOpenRun: (runId: string) => void;
  readonly defaultCanonicalEventType?: string;
}) {
  const [canonicalEventType, setCanonicalEventType] = useState(
    defaultCanonicalEventType || 'canonical.record.v1',
  );
  const [correlationId, setCorrelationId] = useState('corr_1001');
  const [payloadText, setPayloadText] = useState(DEFAULT_EVENT_PAYLOAD);
  const [result, setResult] = useState<TriggerStitchEventResult | null>(null);
  const [problem, setProblem] = useState<ApiProblem | null>(null);

  useEffect(() => {
    if (defaultCanonicalEventType) {
      setCanonicalEventType(defaultCanonicalEventType);
    }
  }, [defaultCanonicalEventType]);

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
              <Label htmlFor="dispatch-event-type">Canonical Event Type</Label>
              <Input
                id="dispatch-event-type"
                value={canonicalEventType}
                onChange={(e) => setCanonicalEventType(e.target.value)}
                placeholder="e.g. canonical.record.created"
                className="font-mono text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="dispatch-corr-id">Correlation ID (Optional)</Label>
              <Input
                id="dispatch-corr-id"
                value={correlationId}
                onChange={(e) => setCorrelationId(e.target.value)}
                placeholder="corr_..."
                className="font-mono text-xs"
              />
            </div>
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <Label htmlFor="dispatch-payload">Canonical JSON Payload</Label>
              <span className="text-xs text-muted-foreground">Monaco Editor</span>
            </div>
            <MonacoCodeEditor
              height={180}
              language="json"
              value={payloadText}
              onChange={setPayloadText}
            />
            {!parsedCandidate.ok && payloadText.trim() ? (
              <p className="text-xs text-destructive">Invalid JSON: {parsedCandidate.reason}</p>
            ) : null}
          </div>

          {result ? (
            <div className="rounded-md border border-border bg-muted/40 p-3 space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-foreground">Dispatch Outcome</span>
                <span className="font-mono text-muted-foreground">
                  Deduplicated: {result.deduplicatedRunIds.length}
                </span>
              </div>

              {result.startedRunIds.length > 0 ? (
                <div className="space-y-1">
                  <span className="text-muted-foreground block">Started Workflow Runs:</span>
                  <div className="flex flex-wrap gap-1.5">
                    {result.startedRunIds.map((runId) => (
                      <button
                        key={runId}
                        type="button"
                        onClick={() => {
                          onOpenChange(false);
                          onOpenRun(runId);
                        }}
                        className="inline-flex items-center gap-1 rounded bg-background px-2 py-0.5 font-mono text-[11px] hover:underline"
                      >
                        <CopyableIdPill value={runId} />
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              {result.signalledStepIds.length > 0 ? (
                <div className="space-y-1">
                  <span className="text-muted-foreground block">Signalled Step Gates:</span>
                  <div className="flex flex-wrap gap-1">
                    {result.signalledStepIds.map((stepId) => (
                      <code key={stepId} className="rounded bg-background px-1.5 py-0.5 font-mono">
                        {stepId}
                      </code>
                    ))}
                  </div>
                </div>
              ) : null}

              {result.startedRunIds.length === 0 && result.signalledStepIds.length === 0 ? (
                <p className="text-muted-foreground italic">
                  No active trigger stitches or gate conditions matched this canonical event.
                </p>
              ) : null}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button
            type="button"
            disabled={
              dispatchMutation.isPending || !parsedCandidate.ok || !canonicalEventType.trim()
            }
            onClick={() => void handleDispatch()}
          >
            {dispatchMutation.isPending ? 'Dispatching...' : 'Dispatch Canonical Event'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
