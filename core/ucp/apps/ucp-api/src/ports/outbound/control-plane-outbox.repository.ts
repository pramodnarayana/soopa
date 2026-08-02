export const OUTBOX_REPOSITORY = 'OUTBOX_REPOSITORY';

export interface OutboxEvent {
  id: string;
  idempotencyKey: string;
  tenantId: string;
  eventType: string;
  payload: Record<string, unknown>;
  status: 'PENDING' | 'PROCESSING' | 'PROCESSED' | 'FAILED';
  createdAt: Date;
  updatedAt: Date;
}

export interface IControlPlaneOutboxRepository {
  fetchPendingEvents(limit: number): Promise<OutboxEvent[]>;
  findById(id: string): Promise<OutboxEvent | null>;
  markAsProcessed(id: string): Promise<void>;
  markAsFailed(id: string, error?: string): Promise<void>;
}
