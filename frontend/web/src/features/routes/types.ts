export interface RouteItem {
  route_id: string;
  trading_partner_id?: string;
  name: string;
  direction: 'INBOUND' | 'OUTBOUND';
  isa_sender_id: string;
  isa_sender_qualifier?: string;
  isa_receiver_id: string;
  isa_receiver_qualifier?: string;
  gs_sender_id?: string;
  gs_receiver_id?: string;
  default_standard?: string;
  default_version?: string;
  transaction_type: string;
  destination_type: string;
  destination_name: string;
  webhook_id?: string;
  as2_partner_id?: string;
  sftp_partner_id?: string;
  status: string;
  active: boolean;
  processing_mode: 'TRANSLATE' | 'PASSTHROUGH';
}

export interface CreateInboundRoutePayload {
  name: string;
  isa_sender_id: string;
  isa_receiver_id: string;
  gs_sender_id?: string;
  gs_receiver_id?: string;
  transaction_type: string;
  processing_mode: 'TRANSLATE' | 'PASSTHROUGH';
  webhook_id?: string;
  as2_partner_id?: string;
  sftp_partner_id?: string;
}

export interface CreateOutboundRoutePayload {
  trading_partner_id: string;
  name: string;
  isa_sender_id: string;
  isa_sender_qualifier?: string;
  isa_receiver_id: string;
  isa_receiver_qualifier?: string;
  gs_sender_id: string;
  gs_receiver_id: string;
  default_standard: string;
  default_version: string;
  transaction_type: string;
  processing_mode: 'TRANSLATE' | 'PASSTHROUGH';
  as2_partner_id?: string;
  sftp_partner_id?: string;
}

export interface UpdateRoutePayload {
  name?: string;
  trading_partner_id?: string;
  isa_sender_id?: string;
  isa_sender_qualifier?: string;
  isa_receiver_id?: string;
  isa_receiver_qualifier?: string;
  gs_sender_id?: string;
  gs_receiver_id?: string;
  default_standard?: string;
  default_version?: string;
  transaction_type?: string;
  processing_mode?: 'TRANSLATE' | 'PASSTHROUGH';
  webhook_id?: string;
  as2_partner_id?: string;
  sftp_partner_id?: string;
  active?: boolean;
}
