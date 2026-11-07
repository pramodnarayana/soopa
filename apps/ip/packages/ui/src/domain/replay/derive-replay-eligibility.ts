import {
  type JsonRecord,
  PipelineLayer,
  type PipelineLayerValue,
  ReplayStage,
  type ReplayStageValue,
  StagePosture,
  type StagePostureValue,
} from '../enums';
import type { IpTrace } from '../trace';

export interface ReplayEligibility {
  readonly stages: readonly ReplayStageValue[];
  readonly modifiableStages: readonly ReplayStageValue[];
  readonly recommendedStage: ReplayStageValue | null;
}

export interface PipelineLayerSummary {
  readonly layer: PipelineLayerValue;
  readonly label: string;
  readonly subtitle: string;
  readonly posture: StagePostureValue;
  readonly countLabel: string;
}

export interface PipelineWaterfallSummary {
  readonly layers: readonly PipelineLayerSummary[];
  readonly hasUnhydratedS3Payloads: boolean;
}

function hasFailedOutbound(trace: IpTrace): boolean {
  return trace.outboundRecords.some(
    (record) => record.status === 'FAILED' || record.failureCategory !== null,
  );
}

function selectRecommendedStage(
  trace: IpTrace,
  stages: readonly ReplayStageValue[],
): ReplayStageValue | null {
  if (hasFailedOutbound(trace) && stages.includes(ReplayStage.RETRY_DELIVER)) {
    return ReplayStage.RETRY_DELIVER;
  }
  if (trace.normalizationRejections.length > 0 && stages.includes(ReplayStage.RETRY_NORMALIZE)) {
    return ReplayStage.RETRY_NORMALIZE;
  }
  if (trace.replicaRejections.length > 0 && stages.includes(ReplayStage.RETRY_INGEST)) {
    return ReplayStage.RETRY_INGEST;
  }
  return stages.at(-1) ?? null;
}

export function deriveEligibleReplayStages(trace: IpTrace): ReplayEligibility {
  const stages: ReplayStageValue[] = [];
  const modifiableStages: ReplayStageValue[] = [];

  if (trace.inboundRecord !== null) {
    stages.push(ReplayStage.RETRY_INGEST);
    modifiableStages.push(ReplayStage.RETRY_INGEST);
  }
  if (trace.replicaRecords.length > 0) {
    stages.push(ReplayStage.RETRY_NORMALIZE);
  }
  if (trace.normalizedRecords.length > 0) {
    stages.push(ReplayStage.RETRY_STITCH);
    modifiableStages.push(ReplayStage.RETRY_STITCH);
  }
  if (trace.outboundRecords.length > 0) {
    stages.push(ReplayStage.RETRY_DELIVER);
  }

  return {
    stages,
    modifiableStages,
    recommendedStage: selectRecommendedStage(trace, stages),
  };
}

function deriveL2Posture(trace: IpTrace): StagePostureValue {
  if (trace.replicaRejections.length > 0) {
    return StagePosture.CRITICAL;
  }
  return trace.replicaRecords.length > 0 ? StagePosture.HEALTHY : StagePosture.SKIPPED;
}

function deriveL3Posture(trace: IpTrace): StagePostureValue {
  if (trace.normalizationRejections.length > 0) {
    return StagePosture.CRITICAL;
  }
  return trace.normalizedRecords.length > 0 ? StagePosture.HEALTHY : StagePosture.SKIPPED;
}

function deriveL4Posture(trace: IpTrace): StagePostureValue {
  const hasStitchActivity =
    trace.outboundRecords.length > 0 ||
    trace.traceEvents.some((evt) => evt.eventType.toLowerCase().includes('stitch'));
  if (hasStitchActivity) {
    return StagePosture.HEALTHY;
  }
  return trace.normalizedRecords.length > 0 ? StagePosture.WARNING : StagePosture.SKIPPED;
}

function deriveL5Posture(trace: IpTrace): StagePostureValue {
  if (trace.outboundRecords.length === 0) {
    return StagePosture.SKIPPED;
  }
  if (hasFailedOutbound(trace)) {
    return StagePosture.CRITICAL;
  }
  const hasPending = trace.outboundRecords.some((rec) => rec.status !== 'DELIVERED');
  return hasPending ? StagePosture.WARNING : StagePosture.HEALTHY;
}

function detectUnhydratedPayloads(trace: IpTrace): boolean {
  const inboundOffloaded =
    trace.inboundRecord !== null &&
    ((trace.inboundRecord.requestS3Key !== null && trace.inboundRecord.requestBody === null) ||
      (trace.inboundRecord.responseS3Key !== null && trace.inboundRecord.responseBody === null));
  if (inboundOffloaded) {
    return true;
  }
  return trace.outboundRecords.some(
    (rec) =>
      (rec.requestS3Key !== null && rec.requestBody === null) ||
      (rec.responseS3Key !== null && rec.responseBody === null),
  );
}

export function computePipelineWaterfallSummary(trace: IpTrace): PipelineWaterfallSummary {
  const layers: PipelineLayerSummary[] = [
    {
      layer: PipelineLayer.L1_INGEST,
      label: 'L1 Wire Ingest',
      subtitle: trace.inboundRecord ? trace.inboundRecord.ingestionMode : 'Inherited / Replay',
      posture: trace.inboundRecord ? StagePosture.HEALTHY : StagePosture.SKIPPED,
      countLabel: trace.inboundRecord ? '1 Wire Capture' : '0',
    },
    {
      layer: PipelineLayer.L2_REPLICA,
      label: 'L2 Universal Replica',
      subtitle: 'Raw Deduplicated State',
      posture: deriveL2Posture(trace),
      countLabel: `${trace.replicaRecords.length} rec · ${trace.replicaRejections.length} rej`,
    },
    {
      layer: PipelineLayer.L3_NORMALIZE,
      label: 'L3 Canonical + GEM',
      subtitle: 'Typed Entity & Cross-Ref',
      posture: deriveL3Posture(trace),
      countLabel: `${trace.normalizedRecords.length} ent · ${trace.entityMappings.length} GEM`,
    },
    {
      layer: PipelineLayer.L4_STITCH,
      label: 'L4 Durable Stitch',
      subtitle: 'DAG Orchestration',
      posture: deriveL4Posture(trace),
      countLabel: `${trace.traceEvents.length} audit evt`,
    },
    {
      layer: PipelineLayer.L5_DELIVER,
      label: 'L5 Outbound Wire',
      subtitle: 'Destination HTTP Audit',
      posture: deriveL5Posture(trace),
      countLabel: `${trace.outboundRecords.length} delivery`,
    },
  ];

  return {
    layers,
    hasUnhydratedS3Payloads: detectUnhydratedPayloads(trace),
  };
}

export function extractModifiablePayloadSeed(trace: IpTrace, stage: ReplayStageValue): JsonRecord {
  if (stage === ReplayStage.RETRY_INGEST) {
    return trace.inboundRecord?.requestBody ?? {};
  }
  return trace.normalizedRecords[0]?.canonicalData ?? {};
}
