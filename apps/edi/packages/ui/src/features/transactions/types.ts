export interface TransactionListResponse {
  items: TransactionListItem[];
}

export interface TransactionListItem {
  id: string;
  trace_id: string;
  direction: 'INBOUND' | 'OUTBOUND';
  transaction_type: string | null;
  sender_id: string | null;
  receiver_id: string | null;
  status: string;
  edi_data?: string | null;
  created_at: string;
}

export interface TransactionDetailResponse {
  // edi_message is nullable: outbound replay creates EdiJson first; the EdiMessage
  // is written asynchronously by the transform worker. The UI must handle this race window.
  edi_message: {
    id: string;
    trace_id: string;
    direction: 'INBOUND' | 'OUTBOUND';
    connection_type: string | null;
    sender_id: string | null;
    receiver_id: string | null;
    gs_sender_id: string | null;
    gs_receiver_id: string | null;
    status: string;
    edi_data: string | null;
    is_replay: boolean;
    original_trace_id: string | null;
    parent_trace_id: string | null;
    created_at: string;
  } | null;
  edi_json: {
    id: string;
    direction: 'INBOUND' | 'OUTBOUND';
    transaction_type: string;
    business_metadata: Record<string, any> | null;
    payload: Record<string, unknown> | null;
    status: string;
    is_replay: boolean;
    original_trace_id: string | null;
    parent_trace_id: string | null;
    created_at: string;
  }[];
  api_gateway: {
    id: string;
    webhook_url: string | null;
    http_status_code: number | null;
    payload: Record<string, unknown> | null;
    response: string | null;
    status: string;
    created_at: string;
  }[];
  trading_partner_name?: string | null;
}

export interface TransactionThreadResponse {
  items: {
    id: string;
    trace_id: string;
    direction: string;
    transaction_type: string | null;
    sender_id: string | null;
    receiver_id: string | null;
    status: string;
    business_metadata: Record<string, unknown> | null;
    created_at: string;
  }[];
}
