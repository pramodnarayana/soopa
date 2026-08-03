import { Card, CardContent, CardHeader, CardTitle } from '@soopa/ui/components/ui/card';
import { Activity, AlertCircle, CheckCircle2, Database, FileJson, Server } from 'lucide-react';
import { Badge } from '../../../components/ui/badge';
import { CodeViewer } from '../../../components/ui/code-viewer';
import type { TransactionDetailResponse } from '../types';

interface Props {
  transaction: TransactionDetailResponse;
}

function IsaGsFieldsGrid({
  senderId,
  receiverId,
  gsSenderId,
  gsReceiverId,
  className = 'grid grid-cols-2 md:grid-cols-4 gap-4 text-sm',
}: {
  senderId?: string | null;
  receiverId?: string | null;
  gsSenderId?: string | null;
  gsReceiverId?: string | null;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="bg-slate-50 p-3 rounded-lg border border-slate-100 shadow-sm">
        <div className="text-slate-500 mb-1 text-xs uppercase font-semibold">ISA Sender</div>
        <div className="font-mono text-slate-900">{senderId || '-'}</div>
      </div>
      <div className="bg-slate-50 p-3 rounded-lg border border-slate-100 shadow-sm">
        <div className="text-slate-500 mb-1 text-xs uppercase font-semibold">ISA Receiver</div>
        <div className="font-mono text-slate-900">{receiverId || '-'}</div>
      </div>
      <div className="bg-slate-50 p-3 rounded-lg border border-slate-100 shadow-sm">
        <div className="text-slate-500 mb-1 text-xs uppercase font-semibold">GS Sender</div>
        <div className="font-mono text-slate-900">{gsSenderId || '-'}</div>
      </div>
      <div className="bg-slate-50 p-3 rounded-lg border border-slate-100 shadow-sm">
        <div className="text-slate-500 mb-1 text-xs uppercase font-semibold">GS Receiver</div>
        <div className="font-mono text-slate-900">{gsReceiverId || '-'}</div>
      </div>
    </div>
  );
}

export function TransactionTimeline({ transaction }: Props) {
  const { edi_message: msg, edi_json: jsons, api_gateway: gateways } = transaction;

  const isOutbound = msg.direction === 'OUTBOUND';
  const primaryStatus = isOutbound ? jsons[0]?.status || msg.status : msg.status;
  const isFailed = ['FAILED', 'ERROR'].includes(primaryStatus?.toUpperCase() || '');
  const colorClass = isFailed ? 'text-red-600' : 'text-emerald-600';

  const renderBadge = (status?: string) => {
    if (!status) return null;
    const upper = status.toUpperCase();
    if (['RECEIVED', 'ACCEPTED', 'PARSED', 'TRANSFORMED', 'DELIVERED'].includes(upper)) {
      return (
        <Badge variant="outline" className="bg-emerald-50 text-emerald-700 border-emerald-200">
          SUCCESS ({upper})
        </Badge>
      );
    }
    if (['FAILED', 'ERROR'].includes(upper)) {
      return (
        <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200">
          FAILURE ({upper})
        </Badge>
      );
    }
    return (
      <Badge variant="outline" className="bg-slate-50 text-slate-700 border-slate-200">
        {upper}
      </Badge>
    );
  };

  // Common UI blocks
  const renderEdiMessageBlock = () => (
    <Card>
      <CardHeader className="pb-3 border-b border-slate-100">
        <div className="flex items-center justify-between">
          <CardTitle className={`text-lg flex items-center gap-2 ${colorClass}`}>
            Received from Trading Partner
          </CardTitle>
          <Badge variant="secondary">{msg.direction}</Badge>
        </div>
      </CardHeader>
      <CardContent className="pt-4 space-y-4">
        <div className="flex items-center gap-3 bg-slate-50 p-3 rounded-lg border border-slate-100">
          <Server className="w-5 h-5 text-slate-400 shrink-0" />
          <div className="text-sm text-slate-600 space-y-0.5">
            <div>
              <span className="font-semibold text-slate-700">Trading Partner:</span>{' '}
              {transaction.trading_partner_name || (
                <span className="text-slate-400 italic">Unknown</span>
              )}
            </div>
            <div>
              <span className="font-semibold text-slate-700">Connection Type:</span>{' '}
              {msg.connection_type && msg.connection_type !== 'UNKNOWN' ? (
                msg.connection_type
              ) : (
                <span className="text-slate-400 italic">Unknown</span>
              )}
            </div>
          </div>
        </div>
        <IsaGsFieldsGrid
          senderId={msg.sender_id}
          receiverId={msg.receiver_id}
          gsSenderId={msg.gs_sender_id}
          gsReceiverId={msg.gs_receiver_id}
        />
        <div className="mt-4">
          <div className="text-sm font-semibold text-slate-700 mb-2">Raw Payload</div>
          <CodeViewer
            language="edi"
            height={250}
            value={msg.edi_data || 'No payload available (might be stored in blob).'}
          />
        </div>
      </CardContent>
    </Card>
  );

  const renderApiGatewayReceiptBlock = () => (
    <Card>
      <CardHeader className="pb-3 border-b border-slate-100">
        <CardTitle className={`text-lg ${colorClass}`}>Received via API Gateway</CardTitle>
      </CardHeader>
      <CardContent className="pt-4 space-y-6">
        {jsons.length === 0 ? (
          <div className="text-center text-slate-500 py-8">No JSON records found.</div>
        ) : (
          jsons.map((json, idx) => {
            const reconstructedPayload = {
              trading_partner_id:
                (json.business_metadata as { _routing?: { trading_partner_id?: string } })?._routing
                  ?.trading_partner_id || 'UNKNOWN',
              transaction_type: json.transaction_type || 'UNKNOWN',
              payload: json.payload,
            };

            return (
              <div key={json.id} className={idx > 0 ? 'pt-6 border-t border-slate-100' : ''}>
                <div className="text-xs font-semibold text-slate-500 uppercase mb-2">
                  Request Payload
                </div>
                <CodeViewer
                  language="json"
                  height={250}
                  value={JSON.stringify(reconstructedPayload, null, 2)}
                />
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );

  const renderEdiJsonBlock = () => (
    <Card>
      <CardHeader className="pb-3 border-b border-slate-100">
        <CardTitle className={`text-lg ${colorClass}`}>
          {isOutbound ? 'Transformed & Metadata Extracted' : 'Transformed to JSON'}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-4 space-y-6">
        {jsons.length === 0 ? (
          <div className="text-center text-slate-500 py-8">No JSON records found.</div>
        ) : (
          jsons.map((json, idx) => (
            <div key={json.id} className={idx > 0 ? 'pt-6 border-t border-slate-100' : ''}>
              <div className="flex items-center justify-between mb-4">
                <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200">
                  {json.transaction_type || 'Unknown Type'}
                </Badge>
                {renderBadge(json.status)}
              </div>

              <IsaGsFieldsGrid
                senderId={json.sender_id}
                receiverId={json.receiver_id}
                gsSenderId={json.gs_sender_id}
                gsReceiverId={json.gs_receiver_id}
                className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm mb-4"
              />

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <div className="text-xs font-semibold text-slate-500 uppercase mb-2">
                    Business Metadata
                  </div>
                  <CodeViewer
                    language="json"
                    height={250}
                    value={JSON.stringify(json.business_metadata || {}, null, 2)}
                  />
                </div>
                <div>
                  <div className="text-xs font-semibold text-slate-500 uppercase mb-2">
                    JSON Payload
                  </div>
                  <CodeViewer
                    language="json"
                    height={250}
                    value={
                      json.payload ? JSON.stringify(json.payload, null, 2) : 'No payload available.'
                    }
                  />
                </div>
              </div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );

  const renderOutboundDeliveryBlock = () => {
    const isDeliveryFailed = ['FAILED', 'ERROR'].includes(msg.status?.toUpperCase() || '');
    const isDelivered = msg.status?.toUpperCase() === 'DELIVERED';
    const deliveryColorClass = isDeliveryFailed
      ? 'text-red-600'
      : isDelivered
        ? 'text-emerald-600'
        : 'text-amber-600';

    return (
      <Card>
        <CardHeader className="pb-3 border-b border-slate-100">
          <CardTitle className={`text-lg ${deliveryColorClass}`}>
            {isDelivered
              ? 'Delivered to '
              : isDeliveryFailed
                ? 'Failed to deliver to '
                : 'Delivering to '}
            {transaction.trading_partner_name ||
              (msg.connection_type && msg.connection_type !== 'UNKNOWN'
                ? msg.connection_type
                : 'Partner')}
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-4 space-y-4">
          <div className="flex items-center justify-between bg-slate-50 p-4 rounded-lg border border-slate-100">
            <div className="flex items-center gap-3">
              {isDelivered ? (
                <CheckCircle2 className="w-6 h-6 text-emerald-500" />
              ) : isDeliveryFailed ? (
                <AlertCircle className="w-6 h-6 text-red-500" />
              ) : (
                <Activity className="w-6 h-6 text-amber-500" />
              )}
              <div>
                <div className="font-medium text-slate-900">Delivery Status</div>
                <div className="text-sm text-slate-500 mt-1">
                  {transaction.trading_partner_name && (
                    <div className="mb-0.5">
                      Trading Partner: {transaction.trading_partner_name}
                    </div>
                  )}
                  <div>
                    Connection Type:{' '}
                    {msg.connection_type && msg.connection_type !== 'UNKNOWN'
                      ? msg.connection_type
                      : 'Default Routing'}
                  </div>
                </div>
              </div>
            </div>
            {renderBadge(msg.status)}
          </div>

          <IsaGsFieldsGrid
            senderId={msg.sender_id}
            receiverId={msg.receiver_id}
            gsSenderId={msg.gs_sender_id}
            gsReceiverId={msg.gs_receiver_id}
            className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm mt-4"
          />
          <div className="mt-4">
            <div className="text-sm font-semibold text-slate-700 mb-2">Raw EDI Payload</div>
            <CodeViewer
              language="edi"
              height={250}
              value={msg.edi_data || 'No payload available (might be stored in blob).'}
            />
          </div>
        </CardContent>
      </Card>
    );
  };

  const renderInboundDeliveryBlock = () => (
    <Card>
      <CardHeader className="pb-3 border-b border-slate-100">
        <CardTitle className={`text-lg ${colorClass}`}>Delivered to Webhook</CardTitle>
      </CardHeader>
      <CardContent className="pt-4 space-y-6">
        {gateways.length === 0 ? (
          <div className="text-center text-slate-500 py-8">
            No gateway/delivery records found for this trace.
          </div>
        ) : (
          gateways.map((gw, idx) => {
            const isSuccess =
              gw.http_status_code && gw.http_status_code >= 200 && gw.http_status_code < 300;
            return (
              <div key={gw.id} className={idx > 0 ? 'pt-6 border-t border-slate-100' : ''}>
                <div className="flex items-center justify-between mb-4 bg-slate-50 p-3 rounded-lg border border-slate-100">
                  <div className="flex items-center gap-3">
                    {isSuccess ? (
                      <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                    ) : (
                      <AlertCircle className="w-5 h-5 text-red-500" />
                    )}
                    <div>
                      <div className="font-medium text-slate-900">
                        {gw.webhook_url ? `Webhook: ${gw.webhook_url}` : 'Webhook'}
                      </div>
                      <div className="text-xs text-slate-500">
                        {new Date(gw.created_at).toLocaleString()}
                      </div>
                    </div>
                  </div>
                  <Badge
                    variant="outline"
                    className={
                      isSuccess
                        ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                        : 'bg-red-50 text-red-700 border-red-200'
                    }
                  >
                    HTTP {gw.http_status_code || '---'}
                  </Badge>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <div className="text-xs font-semibold text-slate-500 uppercase mb-2">
                      Request Payload
                    </div>
                    <CodeViewer
                      language="json"
                      height={200}
                      value={
                        gw.payload ? JSON.stringify(gw.payload, null, 2) : 'No payload available'
                      }
                    />
                  </div>
                  <div>
                    <div className="text-xs font-semibold text-slate-500 uppercase mb-2">
                      Response Body
                    </div>
                    <CodeViewer
                      language="json"
                      height={200}
                      value={gw.response || 'No response recorded.'}
                    />
                  </div>
                </div>
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );

  return (
    <div className="space-y-8 max-w-5xl mx-auto">
      {/* Overview Header */}
      <div className="flex items-center justify-between p-6 bg-white rounded-xl border border-slate-200 shadow-sm">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-slate-900 flex items-center gap-2">
            Trace
          </h2>
          <div className="mt-2 flex items-center gap-4 text-sm text-slate-500">
            <span className="flex items-center gap-1.5">
              <Activity className="w-4 h-4" /> {new Date(msg.created_at).toLocaleString()}
            </span>
          </div>
        </div>
        <div className="text-right">{renderBadge(primaryStatus)}</div>
      </div>

      <div className="relative pl-6 border-l-2 border-slate-100 space-y-12 pb-8">
        {/* STAGE 1 */}
        <div className="relative">
          <div className="absolute -left-[35px] bg-white p-1 rounded-full border-2 border-indigo-500">
            {isOutbound ? (
              <FileJson className="w-5 h-5 text-indigo-600" />
            ) : (
              <Server className="w-5 h-5 text-indigo-600" />
            )}
          </div>
          {isOutbound ? renderApiGatewayReceiptBlock() : renderEdiMessageBlock()}
        </div>

        {/* STAGE 2 */}
        <div className="relative">
          <div className="absolute -left-[35px] bg-white p-1 rounded-full border-2 border-blue-500">
            {isOutbound ? (
              <Database className="w-5 h-5 text-blue-600" />
            ) : (
              <FileJson className="w-5 h-5 text-blue-600" />
            )}
          </div>
          {renderEdiJsonBlock()}
        </div>

        {/* STAGE 3 */}
        <div className="relative">
          <div className="absolute -left-[35px] bg-white p-1 rounded-full border-2 border-emerald-500">
            <Activity className="w-5 h-5 text-emerald-600" />
          </div>
          {isOutbound ? renderOutboundDeliveryBlock() : renderInboundDeliveryBlock()}
        </div>
      </div>
    </div>
  );
}
