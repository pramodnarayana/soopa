export interface EdiHeaderItem {
  id: string;
  trading_partner_id: string;
  name: string;
  isa_sender_id: string;
  isa_sender_qualifier: string;
  isa_receiver_id: string;
  isa_receiver_qualifier: string;
  gs_sender_id: string;
  gs_receiver_id: string;
  transaction_type: string;
  default_standard: string;
  default_version: string;
  created_at: string;
}

export interface CreateEdiHeaderPayload {
  trading_partner_id: string;
  name: string;
  isa_sender_id: string;
  isa_sender_qualifier: string;
  isa_receiver_id: string;
  isa_receiver_qualifier: string;
  gs_sender_id: string;
  gs_receiver_id: string;
  transaction_type: string;
  default_standard: string;
  default_version: string;
}

export interface UpdateEdiHeaderPayload {
  name?: string;
  isa_sender_id?: string;
  isa_sender_qualifier?: string;
  isa_receiver_id?: string;
  isa_receiver_qualifier?: string;
  gs_sender_id?: string;
  gs_receiver_id?: string;
  transaction_type?: string;
  default_standard?: string;
  default_version?: string;
}
