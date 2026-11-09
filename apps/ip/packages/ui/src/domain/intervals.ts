import type {
  BatchManifestStatusValue,
  CimQualityStatusValue,
  PriorityLaneValue,
  TariffBucketValue,
} from './enums';

export interface BatchManifestSummary {
  readonly batchId: string;
  readonly connectionId: string;
  readonly streamName: string;
  readonly priorityLane: PriorityLaneValue;
  readonly status: BatchManifestStatusValue;
  readonly l1RawUri: string;
  readonly l2ReplicaUri: string | null;
  readonly l3CanonicalUri: string | null;
  readonly payloadSha256: string;
  readonly rawIngestedCount: number;
  readonly duplicatesDroppedCount: number;
  readonly validCanonicalCount: number;
  readonly quarantinedHeldCount: number;
  readonly promotedOutageClustersCount: number;
  readonly deliveryReceiptId: string | null;
  readonly traceId: string;
  readonly createdAt: string;
  readonly completedAt: string | null;
}

export interface BatchReconciliationOverview {
  readonly tenantId: string;
  readonly connectionId: string | null;
  readonly totalBatches: number;
  readonly completedBatches: number;
  readonly inFlightBatches: number;
  readonly failedBatches: number;
  readonly rawIngestedTotal: number;
  readonly duplicatesDroppedTotal: number;
  readonly validCanonicalTotal: number;
  readonly quarantinedHeldTotal: number;
  readonly inFlightReadingsTotal: number;
  readonly isZeroLossBalanced: boolean;
  readonly recentBatches: readonly BatchManifestSummary[];
}

export interface IntervalWindowCompleteness {
  readonly tenantId: string;
  readonly connectionId: string;
  readonly streamName: string;
  readonly serviceDate: string;
  readonly feederId: string;
  readonly expectedIntervalsPerDevice: number;
  readonly activeDeviceCount: number;
  readonly expectedIntervalsTotal: number;
  readonly receivedIntervalsTotal: number;
  readonly validIntervalsTotal: number;
  readonly quarantinedIntervalsTotal: number;
  readonly completenessPercentage: number;
}

export interface DailyTouRollup {
  readonly tenantId: string;
  readonly gemDeviceId: string;
  readonly sourceDeviceId: string;
  readonly serviceDate: string;
  readonly feederId: string;
  readonly peakVolume: string;
  readonly shoulderVolume: string;
  readonly offPeakVolume: string;
  readonly netExportVolume: string;
  readonly maxDemandKw: string;
  readonly validIntervals: number;
  readonly quarantinedIntervals: number;
  readonly latestBatchId: string;
  readonly connectionId?: string;
  readonly deliveryReceiptId: string | null;
}

export interface IntervalLineagePoint {
  readonly intervalEndUtc: string;
  readonly gemDeviceId: string;
  readonly sourceDeviceId: string;
  readonly endpointLocationId: string;
  readonly feederId: string;
  readonly substationId: string;
  readonly tariffBucket: TariffBucketValue;
  readonly qualityStatus: CimQualityStatusValue;
  readonly deliveredVolume: string;
  readonly receivedVolume: string;
  readonly reactiveVolume: string;
  readonly voltageV: number;
  readonly quarantineReason: string | null;
  readonly sourceBatchId: string;
  readonly parquetRowOffset: number;
  readonly batchStatus: BatchManifestStatusValue;
  readonly priorityLane: PriorityLaneValue;
  readonly l1RawUri: string;
  readonly l2ReplicaUri: string | null;
  readonly l3CanonicalUri: string | null;
  readonly payloadSha256: string;
  readonly deliveryReceiptId: string | null;
  readonly traceId: string;
}

export interface IntervalLineageTrace {
  readonly tenantId: string;
  readonly sourceDeviceId: string;
  readonly serviceDate: string;
  readonly totalIntervals: number;
  readonly validIntervals: number;
  readonly quarantinedIntervals: number;
  readonly intervals: readonly IntervalLineagePoint[];
}
