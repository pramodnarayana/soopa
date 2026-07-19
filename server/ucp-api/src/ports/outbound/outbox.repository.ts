export const OUTBOX_REPOSITORY = 'OUTBOX_REPOSITORY';

export interface OutboxEvent {
  id: string;
  idempotencyKey: string;
  tenantId: string;
  eventType: string;
  payload: Record<string, any>;
  status: 'PENDING' | 'PROCESSED' | 'FAILED';
  createdAt: Date;
  updatedAt: Date;
}

export interface IOutboxRepository {
  fetchPendingEvents(limit: number): Promise<OutboxEvent[]>;
  markAsProcessed(id: string): Promise<void>;
  markAsFailed(id: string, error?: string): Promise<void>;
}
