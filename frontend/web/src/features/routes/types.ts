export interface RouteItem {
  route_id: string;
  name: string;
  direction: 'INBOUND' | 'OUTBOUND';
  isa_sender_id: string;
  isa_receiver_id: string;
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
  transaction_type: string;
  processing_mode: 'TRANSLATE' | 'PASSTHROUGH';
  webhook_id?: string;
  as2_partner_id?: string;
  sftp_partner_id?: string;
}

export interface CreateOutboundRoutePayload {
  name: string;
  isa_sender_id: string;
  isa_receiver_id: string;
  transaction_type: string;
  processing_mode: 'TRANSLATE' | 'PASSTHROUGH';
  as2_partner_id?: string;
  sftp_partner_id?: string;
}

export interface UpdateRoutePayload {
  name?: string;
  isa_sender_id?: string;
  isa_receiver_id?: string;
  transaction_type?: string;
  processing_mode?: 'TRANSLATE' | 'PASSTHROUGH';
  webhook_id?: string;
  as2_partner_id?: string;
  sftp_partner_id?: string;
  active?: boolean;
}
