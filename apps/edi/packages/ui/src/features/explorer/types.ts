export interface FilterRule {
  id?: string;
  field: string;
  operator:
    | 'eq'
    | 'neq'
    | 'contains'
    | 'not_contains'
    | 'in'
    | 'not_in'
    | 'gt'
    | 'lt'
    | 'gte'
    | 'lte'
    | 'is_null'
    | 'is_not_null';
  value: string | number | boolean | unknown[] | null;
}

export interface ExplorerRequest {
  filters: FilterRule[];
}

export interface ExplorerEdiMessage {
  id: string;
  trace_id: string;
  direction: string;
  transaction_type: string | null;
  sender_id: string | null;
  receiver_id: string | null;
  gs_sender_id: string | null;
  gs_receiver_id: string | null;
  status: string;
  created_at: string | null;
  edi_data: string | null;
  storage_uri: string | null;
}

export interface ExplorerEdiJson {
  id: string;
  trace_id: string;
  direction: string;
  transaction_type: string | null;
  sender_id: string | null;
  receiver_id: string | null;
  gs_sender_id: string | null;
  gs_receiver_id: string | null;
  status: string;
  created_at: string | null;
  business_metadata: Record<string, unknown> | null;
  payload: Record<string, unknown> | null;
}

export interface ExplorerResponse<T> {
  items: T[];
}
