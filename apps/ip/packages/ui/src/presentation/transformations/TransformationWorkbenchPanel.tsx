import {
  type ApiProblem,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  MonacoCodeViewer,
  MonacoJsonDiffViewer,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  StatusBadge,
  StatusTone,
} from '@soopa/ui';
import { FlaskConical, Play } from 'lucide-react';
import React, { useState } from 'react';
import { usePreviewTransformationMutation } from '../../application/use-transformation-queries';
import type { JsonRecord } from '../../domain/enums';
import { parseJsonObject } from '../../domain/replay/parse-json-object';
import type {
  PreviewStreamTransformationInput,
  RegisteredTransformer,
  TransformationPreviewResult,
} from '../../domain/transformation';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { stringifyJsonPretty } from '../shared/status-mapping';

const DEFAULT_SAMPLE_PAYLOAD = JSON.stringify(
  {
    meter_id: 'MTR-700',
    reading_kwh: 142.85,
    captured_at: '2026-10-29T08:00:00Z',
    register_channel: 'A',
  },
  null,
  2,
);

function parseSampleJson(raw: string): JsonRecord | null {
  const parsed = parseJsonObject(raw);
  return parsed.ok ? parsed.value : null;
}

function parseOptionalPositiveInt(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isNaN(parsed) ? null : parsed;
}

function buildPreviewRequest(params: {
  connectionId: string;
  stream: string;
  transformationId: string;
  activeVersion: string;
  shadowVersion: string;
  recordKey: string;
  samplePayload: JsonRecord;
}): PreviewStreamTransformationInput {
  return {
    connectionId: params.connectionId,
    stream: params.stream.trim() || 'default',
    transformationId: params.transformationId,
    transformationVersion: parseOptionalPositiveInt(params.activeVersion) ?? 1,
    recordKey: params.recordKey.trim() || 'sample-1',
    samplePayload: params.samplePayload,
    shadowTransformationVersion: parseOptionalPositiveInt(params.shadowVersion),
  };
}

function ShadowDiffResultCards({ result }: { readonly result: TransformationPreviewResult }) {
  const diffEntries = Object.entries(result.shadowDiffs);

  return (
    <div className="space-y-4">
      {result.rejections.map((rej, idx) => (
        <div
          key={`${rej.reason}-${idx}`}
          className="rounded-xl border border-status-critical-border bg-status-critical-bg px-4 py-3 text-xs text-status-critical-fg"
        >
          <span className="font-mono font-bold">{rej.reason}</span>
          {rej.fieldPath ? <span className="font-mono"> ({rej.fieldPath})</span> : null}:{' '}
          {rej.detail}
        </div>
      ))}

      {result.drafts.map((draft) => (
        <Card key={`${draft.canonicalType}:${draft.sourceId}`}>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle className="font-mono text-sm">
                {draft.canonicalType} · {draft.sourceId}
              </CardTitle>
              <CardDescription>
                Active v{result.transformationVersion} Canonical Entity + Extensions
              </CardDescription>
            </div>
            <StatusBadge label={`${draft.references.length} GEM refs`} tone={StatusTone.HEALTHY} />
          </CardHeader>
          <CardContent>
            <MonacoCodeViewer
              height={220}
              value={stringifyJsonPretty({
                fields: draft.fields,
                extensions: draft.extensions,
                references: draft.references,
              })}
            />
          </CardContent>
        </Card>
      ))}

      {diffEntries.map(([entityKey, diffRecord]) => (
        <Card key={entityKey} className="border-status-shadow-border">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <StatusBadge
                label={`Shadow Diff v${result.transformationVersion} → v${result.shadowTransformationVersion ?? '?'}`}
                tone={StatusTone.SHADOW}
              />
              <span className="font-mono">{entityKey}</span>
            </CardTitle>
            <CardDescription>
              Left: Active v{result.transformationVersion} output · Right: Shadow candidate v
              {result.shadowTransformationVersion ?? '?'} output
            </CardDescription>
          </CardHeader>
          <CardContent>
            <MonacoJsonDiffViewer
              height={280}
              originalValue={stringifyJsonPretty(diffRecord.active ?? {})}
              modifiedValue={stringifyJsonPretty(diffRecord.shadow ?? diffRecord)}
            />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function WorkbenchControlStrip({
  transformers,
  effectiveTransformerId,
  onSelectTransformer,
  stream,
  onStreamChange,
  activeVersion,
  onActiveVersionChange,
  shadowVersion,
  onShadowVersionChange,
}: {
  readonly transformers: readonly RegisteredTransformer[];
  readonly effectiveTransformerId: string;
  readonly onSelectTransformer: (val: string) => void;
  readonly stream: string;
  readonly onStreamChange: (val: string) => void;
  readonly activeVersion: string;
  readonly onActiveVersionChange: (val: string) => void;
  readonly shadowVersion: string;
  readonly onShadowVersionChange: (val: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
      <div className="space-y-1 md:col-span-2">
        <Label>Code Transformer</Label>
        <Select value={effectiveTransformerId} onValueChange={onSelectTransformer}>
          <SelectTrigger aria-label="Select transformer">
            <SelectValue placeholder="Choose transformer" />
          </SelectTrigger>
          <SelectContent>
            {transformers.map((tr) => (
              <SelectItem
                key={`${tr.transformationId}:${tr.transformationVersion}`}
                value={tr.transformationId}
              >
                {tr.transformationId} (v{tr.transformationVersion})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1">
        <Label htmlFor="wb-stream">Stream</Label>
        <Input
          id="wb-stream"
          value={stream}
          onChange={(e) => onStreamChange(e.target.value)}
          className="font-mono text-xs"
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="wb-active-ver">Active Version</Label>
        <Input
          id="wb-active-ver"
          type="number"
          value={activeVersion}
          onChange={(e) => onActiveVersionChange(e.target.value)}
          className="font-mono text-xs"
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="wb-shadow-ver">Shadow Version (Optional)</Label>
        <Input
          id="wb-shadow-ver"
          type="number"
          placeholder="e.g. 2"
          value={shadowVersion}
          onChange={(e) => onShadowVersionChange(e.target.value)}
          className="font-mono text-xs"
        />
      </div>
    </div>
  );
}

function resolveInitialTransformer(transformers: readonly RegisteredTransformer[]): {
  readonly id: string;
  readonly version: string;
} {
  const first = transformers[0];
  if (!first) {
    return { id: '', version: '1' };
  }
  return {
    id: first.transformationId,
    version: String(first.transformationVersion),
  };
}

function WorkbenchEditorSplit({
  recordKey,
  onRecordKeyChange,
  sampleText,
  onSampleTextChange,
  isPayloadValid,
  previewResult,
}: {
  readonly recordKey: string;
  readonly onRecordKeyChange: (val: string) => void;
  readonly sampleText: string;
  readonly onSampleTextChange: (val: string) => void;
  readonly isPayloadValid: boolean;
  readonly previewResult: TransformationPreviewResult | null;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label>Sample L2 Replica Payload (Editable JSON)</Label>
          <Input
            value={recordKey}
            onChange={(e) => onRecordKeyChange(e.target.value)}
            aria-label="Sample record key"
            className="h-7 w-40 font-mono text-xs"
          />
        </div>
        <MonacoCodeViewer
          height={280}
          readOnly={false}
          value={sampleText}
          onChange={onSampleTextChange}
        />
        {!isPayloadValid ? (
          <p className="font-mono text-xs text-status-critical-fg">
            Sample payload must be a valid JSON object.
          </p>
        ) : null}
      </div>

      <div className="space-y-2">
        <Label>Canonical Output & Shadow Comparison</Label>
        {previewResult ? (
          <ShadowDiffResultCards result={previewResult} />
        ) : (
          <div className="flex h-72 items-center justify-center rounded-xl border border-dashed border-border bg-muted/20 p-6 text-center text-xs text-muted-foreground">
            Click Run Dry-Run Preview to inspect canonical fields, typed extensions, GEM references,
            and shadow version diffs.
          </div>
        )}
      </div>
    </div>
  );
}

export interface TransformationWorkbenchPanelProps {
  readonly connectionId: string;
  readonly transformers: readonly RegisteredTransformer[];
}

export function TransformationWorkbenchPanel({
  connectionId,
  transformers,
}: TransformationWorkbenchPanelProps) {
  const initial = resolveInitialTransformer(transformers);
  const [selectedId, setSelectedId] = useState(initial.id);
  const [stream, setStream] = useState('meter_readings');
  const [recordKey, setRecordKey] = useState('MTR-700');
  const [activeVersion, setActiveVersion] = useState(initial.version);
  const [shadowVersion, setShadowVersion] = useState('');
  const [sampleText, setSampleText] = useState(DEFAULT_SAMPLE_PAYLOAD);
  const [problem, setProblem] = useState<ApiProblem | null>(null);
  const [previewResult, setPreviewResult] = useState<TransformationPreviewResult | null>(null);

  const previewMutation = usePreviewTransformationMutation();
  const effectiveTransformerId = selectedId || initial.id;
  const parsedPayload = parseSampleJson(sampleText);
  const isDisabled =
    !connectionId || !effectiveTransformerId || !parsedPayload || previewMutation.isPending;

  const handleRunPreview = async (): Promise<void> => {
    if (!parsedPayload) {
      return;
    }
    setProblem(null);
    const res = await previewMutation.mutateAsync(
      buildPreviewRequest({
        connectionId,
        stream,
        transformationId: effectiveTransformerId,
        activeVersion,
        shadowVersion,
        recordKey,
        samplePayload: parsedPayload,
      }),
    );
    if (!res.ok) {
      setProblem(res.error);
      return;
    }
    setPreviewResult(res.value);
  };

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <CardTitle className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-brand-ink" />
            <span>Dry-Run & Shadow Diff Workbench</span>
          </CardTitle>
          <CardDescription>
            Execute pure L2→L3 code transformers against sample JSON payloads and inspect v1 vs v2
            shadow diffs with zero database writes.
          </CardDescription>
        </div>
        <Button
          type="button"
          size="sm"
          disabled={isDisabled}
          onClick={() => void handleRunPreview()}
          className="gap-1.5"
        >
          <Play className="h-3.5 w-3.5" />
          <span>{previewMutation.isPending ? 'Evaluating...' : 'Run Dry-Run Preview'}</span>
        </Button>
      </CardHeader>

      <CardContent className="space-y-4">
        <ApiProblemBanner problem={problem} />

        <WorkbenchControlStrip
          transformers={transformers}
          effectiveTransformerId={effectiveTransformerId}
          onSelectTransformer={setSelectedId}
          stream={stream}
          onStreamChange={setStream}
          activeVersion={activeVersion}
          onActiveVersionChange={setActiveVersion}
          shadowVersion={shadowVersion}
          onShadowVersionChange={setShadowVersion}
        />

        <WorkbenchEditorSplit
          recordKey={recordKey}
          onRecordKeyChange={setRecordKey}
          sampleText={sampleText}
          onSampleTextChange={setSampleText}
          isPayloadValid={parsedPayload !== null}
          previewResult={previewResult}
        />
      </CardContent>
    </Card>
  );
}
