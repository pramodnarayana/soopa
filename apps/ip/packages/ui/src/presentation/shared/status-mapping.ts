import { StatusTone, type StatusToneValue } from '@soopa/ui';
import { formatDistanceToNowStrict, parseISO } from 'date-fns';
import {
  ConnectionStatus,
  PipelineLayer,
  ReplayStage,
  type ReplayStageValue,
  StagePosture,
  type StagePostureValue,
  StitchRunStatus,
  SyncRunStatus,
  TraceStatus,
  TransformationMode,
} from '../../domain/enums';

const TRACE_STATUS_TONE_MAP: Readonly<Record<string, StatusToneValue>> = {
  [TraceStatus.DELIVERED]: StatusTone.HEALTHY,
  [TraceStatus.NORMALIZED]: StatusTone.HEALTHY,
  [TraceStatus.REPLICATED]: StatusTone.NEUTRAL,
  [TraceStatus.INGESTED]: StatusTone.NEUTRAL,
  [TraceStatus.PENDING]: StatusTone.WARNING,
  [TraceStatus.RETRYING]: StatusTone.WARNING,
  [TraceStatus.FAILED]: StatusTone.CRITICAL,
  [TraceStatus.REJECTED]: StatusTone.CRITICAL,
};

const CONNECTION_STATUS_TONE_MAP: Readonly<Record<string, StatusToneValue>> = {
  [ConnectionStatus.ACTIVE]: StatusTone.HEALTHY,
  [ConnectionStatus.AUTH_EXPIRED]: StatusTone.WARNING,
  [ConnectionStatus.SUSPENDED]: StatusTone.WARNING,
  [ConnectionStatus.DISCONNECTED]: StatusTone.CRITICAL,
  [ConnectionStatus.DEACTIVATED]: StatusTone.NEUTRAL,
};

const SYNC_RUN_STATUS_TONE_MAP: Readonly<Record<string, StatusToneValue>> = {
  [SyncRunStatus.SUCCEEDED]: StatusTone.HEALTHY,
  [SyncRunStatus.RUNNING]: StatusTone.REPLAY,
  [SyncRunStatus.QUEUED]: StatusTone.NEUTRAL,
  [SyncRunStatus.FAILED]: StatusTone.CRITICAL,
  [SyncRunStatus.CANCELLED]: StatusTone.WARNING,
};

const STITCH_RUN_STATUS_TONE_MAP: Readonly<Record<string, StatusToneValue>> = {
  [StitchRunStatus.SUCCEEDED]: StatusTone.HEALTHY,
  [StitchRunStatus.RUNNING]: StatusTone.REPLAY,
  [StitchRunStatus.WAITING]: StatusTone.WARNING,
  [StitchRunStatus.PENDING]: StatusTone.NEUTRAL,
  [StitchRunStatus.FAILED]: StatusTone.CRITICAL,
  [StitchRunStatus.CANCELLED]: StatusTone.NEUTRAL,
};

const TRANSFORMATION_MODE_TONE_MAP: Readonly<Record<string, StatusToneValue>> = {
  [TransformationMode.ACTIVE]: StatusTone.HEALTHY,
  [TransformationMode.SHADOW]: StatusTone.SHADOW,
  [TransformationMode.DISABLED]: StatusTone.NEUTRAL,
};

const STAGE_POSTURE_TONE_MAP: Readonly<Record<StagePostureValue, StatusToneValue>> = {
  [StagePosture.HEALTHY]: StatusTone.HEALTHY,
  [StagePosture.WARNING]: StatusTone.WARNING,
  [StagePosture.CRITICAL]: StatusTone.CRITICAL,
  [StagePosture.SKIPPED]: StatusTone.NEUTRAL,
};

const LAYER_SHORT_LABELS: Readonly<Record<string, string>> = {
  [PipelineLayer.L1_INGEST]: 'L1 Wire Ingest',
  [PipelineLayer.L2_REPLICA]: 'L2 Replica',
  [PipelineLayer.L3_NORMALIZE]: 'L3 Canonical + GEM',
  [PipelineLayer.L4_STITCH]: 'L4 Stitch DAG',
  [PipelineLayer.L5_DELIVER]: 'L5 Outbound Wire',
};

const REPLAY_STAGE_LABELS: Readonly<Record<ReplayStageValue, string>> = {
  [ReplayStage.RETRY_INGEST]: 'L1 · Re-Ingest Raw Wire',
  [ReplayStage.RETRY_NORMALIZE]: 'L2→L3 · Re-Run Transformation',
  [ReplayStage.RETRY_STITCH]: 'L3→L4 · Re-Trigger Stitch DAG',
  [ReplayStage.RETRY_DELIVER]: 'L5 · Retry Destination Delivery',
};

export function mapTraceStatusTone(status: string): StatusToneValue {
  return TRACE_STATUS_TONE_MAP[status] ?? StatusTone.NEUTRAL;
}

export function mapConnectionStatusTone(status: string): StatusToneValue {
  return CONNECTION_STATUS_TONE_MAP[status] ?? StatusTone.NEUTRAL;
}

export function mapSyncRunStatusTone(status: string): StatusToneValue {
  return SYNC_RUN_STATUS_TONE_MAP[status] ?? StatusTone.NEUTRAL;
}

export function mapStitchRunStatusTone(status: string): StatusToneValue {
  return STITCH_RUN_STATUS_TONE_MAP[status] ?? StatusTone.NEUTRAL;
}

export function mapTransformationModeTone(mode: string): StatusToneValue {
  return TRANSFORMATION_MODE_TONE_MAP[mode] ?? StatusTone.NEUTRAL;
}

export function mapStagePostureTone(posture: StagePostureValue): StatusToneValue {
  return STAGE_POSTURE_TONE_MAP[posture];
}

export function formatLayerLabel(layer: string): string {
  return LAYER_SHORT_LABELS[layer] ?? layer;
}

export function formatReplayStageLabel(stage: ReplayStageValue): string {
  return REPLAY_STAGE_LABELS[stage];
}

export function formatRelativeTimestamp(isoValue: string | null | undefined): string {
  if (!isoValue) {
    return '—';
  }
  const parsed = parseISO(isoValue);
  if (Number.isNaN(parsed.getTime())) {
    return isoValue;
  }
  return formatDistanceToNowStrict(parsed, { addSuffix: true });
}

export function formatBytesCompact(bytes: number): string {
  if (bytes < 1_024) {
    return `${bytes} B`;
  }
  if (bytes < 1_048_576) {
    return `${(bytes / 1_024).toFixed(1)} KB`;
  }
  return `${(bytes / 1_048_576).toFixed(2)} MB`;
}

export function stringifyJsonPretty(value: unknown): string {
  if (value === null || value === undefined) {
    return 'null';
  }
  return JSON.stringify(value, null, 2);
}
