import { Button, Card, CopyableIdPill, StatusBadge, StatusTone } from '@soopa/ui';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Copy,
  ExternalLink,
  FileText,
  KeyRound,
  Network,
  Radio,
  Receipt,
  Send,
} from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { useStitchesQuery, useStitchRunsQuery } from '../../application/use-stitch-queries';
import { useIpTraceQuery } from '../../application/use-trace-queries';
import type { NormalizedRecord, OutboundRecord } from '../../domain/trace';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { formatBytesCompact, formatRelativeTimestamp } from '../shared/status-mapping';

export type PipelineStage = 'inbound' | 'replica' | 'entity' | 'outbound';

export interface RecordDetailProps {
  readonly record: NormalizedRecord;
  readonly entityName: string;
  readonly fallbackOutbound?: OutboundRecord;
  readonly fallbackOutbounds?: readonly OutboundRecord[];
  readonly onOpenTraceDetail?: (traceId: string) => void;
  readonly onOpenTraceStitches?: (traceId: string) => void;
  readonly initialStage?: PipelineStage;
}

export function RecordDetail({
  record,
  entityName,
  fallbackOutbound,
  fallbackOutbounds,
  onOpenTraceDetail,
  onOpenTraceStitches,
  initialStage,
}: RecordDetailProps) {
  const { navigation } = useIpWorkspace();
  const [activeStage, setActiveStage] = useState<PipelineStage>(initialStage ?? 'entity');
  const [viewMode, setViewMode] = useState<'saas' | 'json'>('saas');
  const [selectedOutboundIndex, setSelectedOutboundIndex] = useState<number>(0);
  const [copied, setCopied] = useState<string | null>(null);

  const traceQuery = useIpTraceQuery(record.traceId);
  const trace = traceQuery.data;

  const stitchesQuery = useStitchesQuery();
  const runsQuery = useStitchRunsQuery(record.traceId ? { traceId: record.traceId } : undefined);
  const allStitches = stitchesQuery.data ?? [];
  const runsForTrace = runsQuery.data ?? [];

  const resolvedWorkflowId = useMemo(() => {
    if (runsForTrace.length > 0 && runsForTrace[0]?.workflowId) {
      return runsForTrace[0].workflowId;
    }
    if (fallbackOutbounds && fallbackOutbounds.length > 0) {
      for (const out of fallbackOutbounds) {
        const match = allStitches.find(
          (s) =>
            s.workflowId.toLowerCase() === out.appId.toLowerCase() ||
            s.workflowId.toLowerCase().includes(out.appId.toLowerCase()) ||
            out.appId.toLowerCase().includes(s.workflowId.toLowerCase()),
        );
        if (match) return match.workflowId;
      }
    }
    if (record.canonicalType) {
      const match = allStitches.find((s) => s.canonicalEventType === record.canonicalType);
      if (match) return match.workflowId;
    }
    return allStitches[0]?.workflowId ?? 'workflow.shopify_orders_to_sap';
  }, [runsForTrace, fallbackOutbounds, allStitches, record.canonicalType]);

  const inboundRecord = trace?.inboundRecord ?? null;
  const replicaRecord = trace?.replicaRecords?.[0] ?? null;
  const entityMappings = trace?.entityMappings ?? [];

  // Multi-destination resolution supporting 1-to-many fan-out
  const traceOutbounds = trace?.outboundRecords ?? [];
  const outboundRecords: readonly OutboundRecord[] =
    traceOutbounds.length > 0
      ? traceOutbounds
      : fallbackOutbounds && fallbackOutbounds.length > 0
        ? fallbackOutbounds
        : fallbackOutbound
          ? [fallbackOutbound]
          : [];

  const activeOutbound = outboundRecords[selectedOutboundIndex] ?? outboundRecords[0] ?? null;

  const hasFailedOutbound = outboundRecords.some(
    (o) => o.status === 'FAILED' || (o.responseStatusCode != null && o.responseStatusCode >= 400),
  );
  const allOutboundsDelivered =
    outboundRecords.length > 0 &&
    outboundRecords.every((o) => o.status === 'DELIVERED' || o.responseStatusCode === 200);

  const isActiveOutboundFailed =
    activeOutbound &&
    (activeOutbound.status === 'FAILED' ||
      (activeOutbound.responseStatusCode !== null && activeOutbound.responseStatusCode >= 400));
  const isActiveOutboundDelivered =
    activeOutbound &&
    (activeOutbound.status === 'DELIVERED' || activeOutbound.responseStatusCode === 200);

  const handleCopy = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(null), 2000);
  };

  const rawData = (record.canonicalData ?? {}) as Record<string, any>;

  // Data-driven entity extraction from actual record
  const docIdentifier =
    rawData.invoiceNumber ||
    rawData.invoice_number ||
    rawData.orderNumber ||
    rawData.order_number ||
    rawData.documentNumber ||
    rawData.load_id ||
    rawData.id ||
    record.sourceId;

  const statusLabel = String(
    rawData.status || rawData.financial_status || rawData.state || 'PROCESSED',
  ).toUpperCase();
  const isStatusHealthy = [
    'APPROVED',
    'PAID',
    'DELIVERED',
    'COMPLETED',
    'ACTIVE',
    'SYNCHRONIZED',
  ].includes(statusLabel);

  // Dynamic Counterparty / Customer
  const customerName =
    typeof rawData.customerName === 'string'
      ? rawData.customerName
      : typeof rawData.customer_name === 'string'
        ? rawData.customer_name
        : typeof rawData.customer === 'string'
          ? rawData.customer
          : typeof rawData.customer === 'object' &&
              rawData.customer !== null &&
              'name' in rawData.customer
            ? String(rawData.customer.name)
            : null;

  const customerEmail =
    typeof rawData.customerEmail === 'string'
      ? rawData.customerEmail
      : typeof rawData.email === 'string'
        ? rawData.email
        : typeof rawData.customer === 'object' &&
            rawData.customer !== null &&
            'email' in rawData.customer
          ? String(rawData.customer.email)
          : null;

  const customerId =
    typeof rawData.customerRef === 'string'
      ? rawData.customerRef
      : typeof rawData.customerId === 'string'
        ? rawData.customerId
        : typeof rawData.customer_id === 'string'
          ? rawData.customer_id
          : null;

  // Dynamic Dates
  const issueDate = rawData.issueDate || rawData.issue_date || rawData.date || null;
  const dueDate = rawData.dueDate || rawData.due_date || null;
  const paymentTerms = rawData.paymentTerms || rawData.payment_terms || null;
  const orderRef = rawData.orderNumber || rawData.order_number || rawData.orderRef || null;

  // Dynamic Financials
  const currency = typeof rawData.currency === 'string' ? rawData.currency.toUpperCase() : null;
  const totalAmount =
    typeof rawData.total === 'number'
      ? rawData.total
      : typeof rawData.total_amount === 'number'
        ? rawData.total_amount
        : typeof rawData.amount === 'number'
          ? rawData.amount
          : null;

  const subtotalAmount =
    typeof rawData.subtotal === 'number'
      ? rawData.subtotal
      : typeof rawData.subtotal_amount === 'number'
        ? rawData.subtotal_amount
        : null;

  const taxAmount = typeof rawData.tax === 'number' ? rawData.tax : null;

  // Real Line Items from actual canonical payload
  const rawItems = Array.isArray(rawData.items)
    ? rawData.items
    : Array.isArray(rawData.line_items)
      ? rawData.line_items
      : null;

  const hasLineItems = rawItems !== null && rawItems.length > 0;

  // Extract non-complex metadata attributes for structured grid fallback
  const scalarAttributes = Object.entries(rawData).filter(([key, value]) => {
    if (['items', 'line_items', 'customer'].includes(key)) return false;
    if (typeof value === 'object' && value !== null) return false;
    return value !== null && value !== undefined && value !== '';
  });

  return (
    <div className="space-y-4">
      {/* ── Top Header Bar: Trace & Direct Workflow Action Link ── */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-1 border-b border-border/40">
        <div className="flex items-center gap-2 text-xs">
          <span className="font-semibold text-foreground">
            {entityName} #{docIdentifier}
          </span>
          <span className="text-muted-foreground font-mono">Trace ID:</span>
          <CopyableIdPill value={record.traceId} truncateLength={16} />
        </div>
        {record.traceId && (
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={() => {
              if (navigation.toStitchDefinition) {
                navigation.toStitchDefinition(resolvedWorkflowId, {
                  traceId: record.traceId,
                  tab: 'canvas',
                });
              } else if (onOpenTraceStitches) {
                onOpenTraceStitches(record.traceId);
              } else {
                window.location.assign(
                  `/tenant/ip/stitches/definitions/${encodeURIComponent(resolvedWorkflowId)}?traceId=${encodeURIComponent(record.traceId)}`,
                );
              }
            }}
            className="gap-1.5 text-xs h-7 px-2.5 hover:bg-muted/60"
          >
            <Network className="h-3.5 w-3.5 text-primary" />
            <span>Workflow (Stitches)</span>
            <ExternalLink className="h-3 w-3 text-muted-foreground" />
          </Button>
        )}
      </div>

      {/* ── 1. Pipeline Stages (Clean & Elegant with Green Tick Marks) ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {/* Stage 1: Inbound */}
        <button
          type="button"
          onClick={() => setActiveStage('inbound')}
          className={`flex items-center gap-2 p-2.5 rounded-lg border transition-all text-left ${
            activeStage === 'inbound'
              ? 'bg-primary/10 border-primary font-bold shadow-xs'
              : 'bg-muted/40 border-border/50 hover:bg-muted/70 text-foreground'
          }`}
        >
          <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
          <span className="text-xs font-semibold truncate">Inbound</span>
        </button>

        {/* Stage 2: Replica */}
        <button
          type="button"
          onClick={() => setActiveStage('replica')}
          className={`flex items-center gap-2 p-2.5 rounded-lg border transition-all text-left ${
            activeStage === 'replica'
              ? 'bg-primary/10 border-primary font-bold shadow-xs'
              : 'bg-muted/40 border-border/50 hover:bg-muted/70 text-foreground'
          }`}
        >
          <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
          <span className="text-xs font-semibold truncate">Replica</span>
        </button>

        {/* Stage 3: Actual Entity Name (e.g. Invoice) */}
        <button
          type="button"
          onClick={() => setActiveStage('entity')}
          className={`flex items-center gap-2 p-2.5 rounded-lg border transition-all text-left ${
            activeStage === 'entity'
              ? 'bg-primary/10 border-primary font-bold shadow-xs'
              : 'bg-muted/40 border-border/50 hover:bg-muted/70 text-foreground'
          }`}
        >
          <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
          <span className="text-xs font-semibold truncate">{entityName}</span>
        </button>

        {/* Stage 4: Outbound */}
        <button
          type="button"
          onClick={() => setActiveStage('outbound')}
          className={`flex items-center gap-2 p-2.5 rounded-lg border transition-all text-left ${
            activeStage === 'outbound'
              ? hasFailedOutbound
                ? 'bg-destructive/10 border-destructive text-destructive font-bold shadow-xs'
                : 'bg-primary/10 border-primary font-bold shadow-xs'
              : hasFailedOutbound
                ? 'bg-destructive/10 border-destructive/30 text-destructive'
                : 'bg-muted/40 border-border/50 hover:bg-muted/70 text-foreground'
          }`}
        >
          {hasFailedOutbound ? (
            <AlertTriangle className="h-4 w-4 text-destructive shrink-0" />
          ) : (
            <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
          )}
          <span className="text-xs font-semibold truncate">
            {outboundRecords.length > 1 ? `Outbound (${outboundRecords.length})` : 'Outbound'}
          </span>
        </button>
      </div>

      {/* ── 2. STAGE 3: Pure SaaS-Grade Normalized Entity View (Default) ──── */}
      {activeStage === 'entity' && (
        <Card className="rounded-xl border border-border bg-card">
          {/* Document Header */}
          <div className="p-4 border-b border-border/60 bg-muted/20">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-xl bg-primary/10 text-primary">
                  <Receipt className="h-5 w-5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-base font-bold text-foreground">
                      {entityName} #{docIdentifier}
                    </h3>
                    <StatusBadge
                      label={statusLabel}
                      tone={isStatusHealthy ? StatusTone.HEALTHY : StatusTone.NEUTRAL}
                    />
                  </div>
                  <div className="text-xs text-muted-foreground flex flex-wrap items-center gap-2 mt-0.5">
                    {customerName && (
                      <span>
                        Customer: <strong className="text-foreground">{customerName}</strong>
                        {customerId && ` (${customerId})`}
                      </span>
                    )}
                    {orderRef && (
                      <>
                        <span>·</span>
                        <span>Ref: {orderRef}</span>
                      </>
                    )}
                    <span>·</span>
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {record.canonicalType}
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-4">
                {totalAmount !== null && (
                  <div className="text-right">
                    <div className="text-lg font-bold text-foreground">
                      $
                      {totalAmount.toLocaleString('en-US', {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}{' '}
                      {currency || 'USD'}
                    </div>
                    {(issueDate || dueDate) && (
                      <div className="text-[11px] text-muted-foreground">
                        {issueDate && `Issued ${issueDate}`}
                        {issueDate && dueDate && ' · '}
                        {dueDate && `Due ${dueDate}`}
                      </div>
                    )}
                  </div>
                )}

                {/* View Switcher: Document vs Raw JSON */}
                <div className="flex items-center rounded-lg border border-border bg-muted/40 p-0.5">
                  <button
                    type="button"
                    onClick={() => setViewMode('saas')}
                    className={`px-2.5 py-1 text-xs font-medium rounded-md transition-all ${
                      viewMode === 'saas'
                        ? 'bg-card text-foreground shadow-xs'
                        : 'text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    Document
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewMode('json')}
                    className={`px-2.5 py-1 text-xs font-medium rounded-md transition-all ${
                      viewMode === 'json'
                        ? 'bg-card text-foreground shadow-xs'
                        : 'text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    JSON
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Document Content */}
          {viewMode === 'saas' ? (
            <div className="p-4 space-y-4">
              {/* Customer & Billing Metadata (if present) */}
              {(customerName || customerEmail || paymentTerms || orderRef) && (
                <div className="p-3.5 rounded-xl bg-muted/20 border border-border/40 text-xs">
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2.5">
                    {customerName && (
                      <div className="grid grid-cols-[130px_1fr] items-center gap-2">
                        <span className="text-muted-foreground font-medium">Customer</span>
                        <div className="truncate">
                          <span className="font-semibold text-foreground">{customerName}</span>
                          {customerEmail && (
                            <span className="text-muted-foreground text-[11px] ml-1.5 font-normal">
                              ({customerEmail})
                            </span>
                          )}
                        </div>
                      </div>
                    )}
                    {paymentTerms && (
                      <div className="grid grid-cols-[130px_1fr] items-center gap-2">
                        <span className="text-muted-foreground font-medium">Payment Terms</span>
                        <span className="font-semibold text-foreground truncate">
                          {paymentTerms}
                        </span>
                      </div>
                    )}
                    {orderRef && (
                      <div className="grid grid-cols-[130px_1fr] items-center gap-2">
                        <span className="text-muted-foreground font-medium">Source Reference</span>
                        <span className="font-semibold text-foreground truncate">{orderRef}</span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Line Items Table (rendered when real items exist) */}
              {hasLineItems ? (
                <div>
                  <div className="text-xs font-semibold text-foreground mb-2">
                    Line Items ({rawItems.length})
                  </div>
                  <div className="rounded-lg border border-border">
                    <table className="w-full text-xs">
                      <thead className="bg-muted/40 border-b border-border text-[11px] text-muted-foreground">
                        <tr>
                          <th className="py-2 px-3 text-left font-semibold">DESCRIPTION</th>
                          <th className="py-2 px-3 text-left font-semibold">SKU / CODE</th>
                          <th className="py-2 px-3 text-right font-semibold">QTY</th>
                          <th className="py-2 px-3 text-right font-semibold">UNIT PRICE</th>
                          <th className="py-2 px-3 text-right font-semibold">TOTAL</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border/40">
                        {rawItems.map((item: any, idx: number) => {
                          const desc =
                            item.description ||
                            item.name ||
                            item.title ||
                            item.sku ||
                            `Item #${idx + 1}`;
                          const sku = item.sku || item.item_code || item.code || '—';
                          const qty = Number(item.quantity ?? item.qty ?? 1);
                          const unitPrice =
                            typeof item.unitPrice === 'number'
                              ? item.unitPrice
                              : typeof item.unit_price === 'number'
                                ? item.unit_price
                                : typeof item.price === 'number'
                                  ? item.price
                                  : null;
                          const lineTotal =
                            typeof item.total === 'number'
                              ? item.total
                              : typeof item.amount === 'number'
                                ? item.amount
                                : unitPrice !== null
                                  ? unitPrice * qty
                                  : null;

                          return (
                            <tr key={idx} className="hover:bg-muted/20">
                              <td className="py-2.5 px-3 font-medium text-foreground">{desc}</td>
                              <td className="py-2.5 px-3 font-mono text-[11px] text-muted-foreground">
                                {sku}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono text-muted-foreground">
                                {qty}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono text-muted-foreground">
                                {unitPrice !== null ? `$${unitPrice.toFixed(2)}` : '—'}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono font-semibold text-foreground">
                                {lineTotal !== null ? `$${lineTotal.toFixed(2)}` : '—'}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                /* Attribute Grid Fallback (cleanly displays real fields without fabricating fake items) */
                <div>
                  <div className="text-xs font-semibold text-foreground mb-2">
                    Record Attributes
                  </div>
                  <div className="p-3.5 rounded-xl bg-muted/20 border border-border/40 text-xs">
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2.5">
                      {scalarAttributes.map(([key, value]) => (
                        <div key={key} className="grid grid-cols-[130px_1fr] items-center gap-2">
                          <span className="text-muted-foreground font-medium truncate">
                            {key.replace(/([A-Z])/g, ' $1').replace(/_/g, ' ')}
                          </span>
                          <span className="font-semibold text-foreground truncate font-mono">
                            {String(value)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* Financial Summary */}
              {totalAmount !== null && (
                <div className="flex justify-end pt-2">
                  <div className="w-64 space-y-1.5 text-xs">
                    {subtotalAmount !== null && (
                      <div className="flex justify-between text-muted-foreground">
                        <span>Subtotal</span>
                        <span className="font-mono">${subtotalAmount.toFixed(2)}</span>
                      </div>
                    )}
                    {taxAmount !== null && (
                      <div className="flex justify-between text-muted-foreground">
                        <span>Tax</span>
                        <span className="font-mono">${taxAmount.toFixed(2)}</span>
                      </div>
                    )}
                    <div className="flex justify-between font-bold text-foreground text-sm pt-2 border-t border-border">
                      <span>Total</span>
                      <span className="font-mono">
                        ${totalAmount.toFixed(2)} {currency || 'USD'}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* ── Cross-System Identity Mapping (GEM) ── */}
              <div className="pt-4 border-t border-border/60 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <KeyRound className="h-4 w-4 text-primary" />
                    <span className="text-xs font-bold text-foreground">GEM</span>
                  </div>
                  {entityMappings.length > 0 ? (
                    <StatusBadge
                      label={`${entityMappings.length} ${entityMappings.length === 1 ? 'MAPPING' : 'MAPPINGS'} RESOLVED`}
                      tone={StatusTone.HEALTHY}
                    />
                  ) : (
                    <span className="text-[11px] text-muted-foreground font-mono">
                      1:1 Correlation
                    </span>
                  )}
                </div>

                {entityMappings.length > 0 ? (
                  <div className="space-y-3">
                    {entityMappings.map((gem) => {
                      const domainLabel = gem.entityDomain
                        .replace(/^domain[._]/i, '')
                        .replace(/[._]/g, ' ')
                        .toUpperCase();
                      const isResolved = Boolean(gem.destEntityId);

                      return (
                        <div
                          key={gem.id}
                          className="rounded-xl border border-border bg-card overflow-hidden"
                        >
                          <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-border">
                            {/* Left: Source Entity Details */}
                            <div className="p-4 space-y-3">
                              <div className="text-xs font-bold text-foreground uppercase tracking-wide pb-2 border-b border-border/60">
                                Source Entity Details
                              </div>
                              <div className="space-y-2.5 text-xs">
                                <div className="grid grid-cols-[130px_1fr] items-center gap-2">
                                  <span className="text-muted-foreground font-medium">System</span>
                                  <span className="font-mono text-foreground font-semibold truncate">
                                    {gem.sourceConnectionId}
                                  </span>
                                </div>
                                <div className="grid grid-cols-[130px_1fr] items-center gap-2">
                                  <span className="text-muted-foreground font-medium">
                                    Entity Type
                                  </span>
                                  <span className="font-mono text-foreground font-semibold">
                                    {domainLabel || 'ENTITY'}
                                  </span>
                                </div>
                                <div className="grid grid-cols-[130px_1fr] items-center gap-2">
                                  <span className="text-muted-foreground font-medium">
                                    Entity ID
                                  </span>
                                  <div>
                                    <CopyableIdPill value={gem.sourceEntityId} />
                                  </div>
                                </div>
                              </div>
                            </div>

                            {/* Right: Destination Entity Details */}
                            <div className="p-4 space-y-3 bg-muted/10">
                              <div className="flex items-center justify-between pb-2 border-b border-border/60">
                                <span className="text-xs font-bold text-foreground uppercase tracking-wide">
                                  Destination Entity Details
                                </span>
                                <StatusBadge
                                  label={isResolved ? 'RESOLVED' : 'PENDING'}
                                  tone={isResolved ? StatusTone.HEALTHY : StatusTone.WARNING}
                                />
                              </div>
                              <div className="space-y-2.5 text-xs">
                                <div className="grid grid-cols-[130px_1fr] items-center gap-2">
                                  <span className="text-muted-foreground font-medium">System</span>
                                  <span className="font-mono text-foreground font-semibold truncate">
                                    {gem.destConnectionId || 'Target System'}
                                  </span>
                                </div>
                                <div className="grid grid-cols-[130px_1fr] items-center gap-2">
                                  <span className="text-muted-foreground font-medium">
                                    Entity Type
                                  </span>
                                  <span className="font-mono text-foreground font-semibold">
                                    {domainLabel || 'ENTITY'}
                                  </span>
                                </div>
                                <div className="grid grid-cols-[130px_1fr] items-center gap-2">
                                  <span className="text-muted-foreground font-medium">
                                    Entity ID
                                  </span>
                                  <div>
                                    {gem.destEntityId ? (
                                      <CopyableIdPill value={gem.destEntityId} />
                                    ) : (
                                      <span className="text-amber-500 font-medium font-sans">
                                        Pending Resolution
                                      </span>
                                    )}
                                  </div>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="p-3 text-xs text-muted-foreground rounded-lg border border-dashed border-border/80">
                    Source identifier{' '}
                    <strong className="font-mono text-foreground">{record.sourceId}</strong> serves
                    as direct authoritative canonical key across pipeline stages.
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="p-4 space-y-2">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>Canonical Payload Schema</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="xs"
                  onClick={() => handleCopy(JSON.stringify(rawData, null, 2), 'canonical')}
                  className="gap-1 text-xs h-6 px-2"
                >
                  <Copy className="h-3 w-3" />
                  <span>{copied === 'canonical' ? 'Copied' : 'Copy JSON'}</span>
                </Button>
              </div>
              <pre className="text-xs font-mono bg-muted/40 p-3.5 rounded-lg border border-border/60 text-foreground leading-relaxed">
                {JSON.stringify(rawData, null, 2)}
              </pre>
            </div>
          )}
        </Card>
      )}

      {/* ── 3. STAGE 1: Inbound Wire Packet View ─────────────────────── */}
      {activeStage === 'inbound' && (
        <Card className="rounded-xl border border-border bg-card p-4 space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-border/50">
            <div className="flex items-center gap-2">
              <Radio className="h-4 w-4 text-primary" />
              <span className="text-xs font-bold text-foreground">Inbound Wire Packet</span>
              <StatusBadge
                label={inboundRecord?.ingestionMode ?? 'WEBHOOK'}
                tone={StatusTone.HEALTHY}
              />
            </div>
            {inboundRecord && (
              <span className="text-xs text-muted-foreground font-mono">
                Received {formatRelativeTimestamp(inboundRecord.receivedAt)}
              </span>
            )}
          </div>

          {inboundRecord ? (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 text-xs">
              {/* ── LEFT: Inbound Request ── */}
              <div className="rounded-xl border border-border bg-card p-3.5 space-y-3">
                <div className="flex items-center justify-between pb-2 border-b border-border/60">
                  <div className="flex items-center gap-1.5">
                    <span className="font-bold text-foreground text-xs uppercase tracking-wide">
                      Request
                    </span>
                    <span className="font-mono text-[10px] text-muted-foreground">
                      ({formatBytesCompact(inboundRecord.requestSizeBytes)})
                    </span>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="xs"
                    onClick={() =>
                      handleCopy(
                        JSON.stringify(inboundRecord.requestBody, null, 2),
                        'inboundRequest',
                      )
                    }
                    className="gap-1 text-xs h-6 px-2"
                  >
                    <Copy className="h-3 w-3" />
                    <span>{copied === 'inboundRequest' ? 'Copied' : 'Copy'}</span>
                  </Button>
                </div>

                {/* Inbound Request Headers */}
                <div className="space-y-1">
                  <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
                    Request Headers
                  </span>
                  <div className="p-2.5 rounded-lg bg-muted/30 border border-border/60 font-mono text-[11px] max-h-32 overflow-auto space-y-0.5">
                    {Object.entries(inboundRecord.requestHeaders || {}).length > 0 ? (
                      Object.entries(inboundRecord.requestHeaders || {}).map(([key, val]) => (
                        <div key={key} className="flex justify-between gap-2">
                          <span className="text-primary font-semibold truncate">{key}:</span>
                          <span className="text-muted-foreground truncate">{String(val)}</span>
                        </div>
                      ))
                    ) : (
                      <div className="text-muted-foreground italic">No HTTP headers recorded</div>
                    )}
                  </div>
                </div>

                {/* Inbound Request Body */}
                <div className="space-y-1">
                  <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
                    Request
                  </span>
                  <pre className="text-xs font-mono bg-muted/40 p-3 rounded-lg border border-border/60 text-foreground leading-relaxed max-h-60 overflow-auto">
                    {JSON.stringify(inboundRecord.requestBody || {}, null, 2)}
                  </pre>
                </div>
              </div>

              {/* ── RIGHT: Inbound Response ── */}
              <div className="rounded-xl border border-border bg-card p-3.5 space-y-3">
                <div className="flex items-center justify-between pb-2 border-b border-border/60">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-foreground text-xs uppercase tracking-wide">
                      Response
                    </span>
                    <StatusBadge
                      label={
                        inboundRecord.responseStatusCode
                          ? `HTTP ${inboundRecord.responseStatusCode}`
                          : 'HTTP 200 OK'
                      }
                      tone={
                        inboundRecord.responseStatusCode && inboundRecord.responseStatusCode >= 400
                          ? StatusTone.CRITICAL
                          : StatusTone.HEALTHY
                      }
                    />
                    {inboundRecord.durationMs != null && (
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {inboundRecord.durationMs}ms
                      </span>
                    )}
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="xs"
                    onClick={() =>
                      handleCopy(
                        JSON.stringify(
                          inboundRecord.responseBody ?? {
                            statusCode: inboundRecord.responseStatusCode ?? 200,
                            status: 'ACCEPTED',
                            traceId: inboundRecord.traceId,
                          },
                          null,
                          2,
                        ),
                        'inboundResponse',
                      )
                    }
                    className="gap-1 text-xs h-6 px-2"
                  >
                    <Copy className="h-3 w-3" />
                    <span>{copied === 'inboundResponse' ? 'Copied' : 'Copy'}</span>
                  </Button>
                </div>

                {/* Inbound Response Headers */}
                <div className="space-y-1">
                  <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
                    Response Headers
                  </span>
                  <div className="p-2.5 rounded-lg bg-muted/30 border border-border/60 font-mono text-[11px] max-h-32 overflow-auto space-y-0.5">
                    {Object.entries(inboundRecord.responseHeaders || {}).length > 0 ? (
                      Object.entries(inboundRecord.responseHeaders || {}).map(([key, val]) => (
                        <div key={key} className="flex justify-between gap-2">
                          <span className="text-emerald-600 dark:text-emerald-400 font-semibold truncate">
                            {key}:
                          </span>
                          <span className="text-muted-foreground truncate">{String(val)}</span>
                        </div>
                      ))
                    ) : (
                      <div className="text-muted-foreground italic font-sans text-[11px]">
                        Server returned 200/202 standard HTTP response headers
                      </div>
                    )}
                  </div>
                </div>

                {/* Inbound Response */}
                <div className="space-y-1">
                  <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
                    Response
                  </span>
                  <pre className="text-xs font-mono bg-muted/40 p-3 rounded-lg border border-border/60 text-foreground leading-relaxed max-h-60 overflow-auto">
                    {JSON.stringify(
                      inboundRecord.responseBody ?? {
                        statusCode: inboundRecord.responseStatusCode ?? 200,
                        status:
                          inboundRecord.responseStatusCode &&
                          inboundRecord.responseStatusCode >= 400
                            ? 'REJECTED'
                            : 'ACCEPTED',
                        traceId: inboundRecord.traceId,
                        durationMs: inboundRecord.durationMs,
                      },
                      null,
                      2,
                    )}
                  </pre>
                </div>
              </div>
            </div>
          ) : (
            <div className="py-6 text-center text-xs text-muted-foreground">
              Inbound wire packet payload is archived or unavailable.
            </div>
          )}
        </Card>
      )}

      {/* ── 4. STAGE 2: Replica Raw Storage View ─────────────────────── */}
      {activeStage === 'replica' && (
        <Card className="rounded-xl border border-border bg-card p-4 space-y-3">
          <div className="flex items-center justify-between pb-2 border-b border-border/50">
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-primary" />
              <span className="text-xs font-bold text-foreground">Replica Document Snapshot</span>
              <StatusBadge label="POSTGRES DATA PLANE" tone={StatusTone.HEALTHY} />
            </div>
            {replicaRecord && (
              <span className="text-xs text-muted-foreground font-mono">
                Extracted {formatRelativeTimestamp(replicaRecord.extractedAt)}
              </span>
            )}
          </div>

          {replicaRecord ? (
            <div className="space-y-3 text-xs">
              <div className="p-3.5 rounded-xl bg-muted/20 border border-border/40 text-xs">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-x-6 gap-y-2.5">
                  <div className="grid grid-cols-[130px_1fr] items-center gap-2">
                    <span className="text-muted-foreground font-medium">Stream</span>
                    <span className="font-mono font-semibold text-foreground truncate">
                      {replicaRecord.stream}
                    </span>
                  </div>
                  <div className="grid grid-cols-[130px_1fr] items-center gap-2">
                    <span className="text-muted-foreground font-medium">Record ID</span>
                    <span className="font-mono font-semibold text-foreground truncate">
                      {replicaRecord.recordKey}
                    </span>
                  </div>
                  <div className="grid grid-cols-[130px_1fr] items-center gap-2">
                    <span className="text-muted-foreground font-medium">Extracted</span>
                    <span className="font-mono text-muted-foreground truncate">
                      {formatRelativeTimestamp(replicaRecord.extractedAt)}
                    </span>
                  </div>
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
                    Raw Stored Payload
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="xs"
                    onClick={() =>
                      handleCopy(JSON.stringify(replicaRecord.data, null, 2), 'replica')
                    }
                    className="gap-1 text-xs h-5 px-2"
                  >
                    <Copy className="h-3 w-3" />
                    <span>{copied === 'replica' ? 'Copied' : 'Copy'}</span>
                  </Button>
                </div>
                <pre className="text-xs font-mono bg-muted/40 p-3 rounded-lg border border-border/60 text-foreground leading-relaxed">
                  {JSON.stringify(replicaRecord.data, null, 2)}
                </pre>
              </div>
            </div>
          ) : (
            <div className="py-6 text-center text-xs text-muted-foreground">
              Replica storage record not located.
            </div>
          )}
        </Card>
      )}

      {/* ── 5. STAGE 4: Multi-Destination Outbound Delivery View ──────── */}
      {activeStage === 'outbound' && (
        <Card className="rounded-xl border border-border bg-card p-4 space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-border/50">
            <div className="flex items-center gap-2">
              <Send className="h-4 w-4 text-primary" />
              <span className="text-xs font-bold text-foreground">Target Endpoint Delivery</span>
              {activeOutbound ? (
                <StatusBadge
                  label={
                    isActiveOutboundFailed
                      ? `FAILED (${activeOutbound.responseStatusCode ?? 503})`
                      : isActiveOutboundDelivered
                        ? 'DELIVERED (200 OK)'
                        : activeOutbound.status
                  }
                  tone={
                    isActiveOutboundFailed
                      ? StatusTone.CRITICAL
                      : isActiveOutboundDelivered
                        ? StatusTone.HEALTHY
                        : StatusTone.NEUTRAL
                  }
                />
              ) : (
                <StatusBadge label="PROCESSING" tone={StatusTone.NEUTRAL} />
              )}
            </div>
            {activeOutbound && (
              <span className="text-xs font-mono text-muted-foreground">
                Dispatched {formatRelativeTimestamp(activeOutbound.sentAt)}
              </span>
            )}
          </div>

          {/* Multi-Destination Switcher (rendered when 1-to-many fan-out exists) */}
          {outboundRecords.length > 1 && (
            <div className="flex flex-wrap items-center gap-1.5 p-2 rounded-lg bg-muted/30 border border-border/50">
              <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mr-1">
                Destinations ({outboundRecords.length}):
              </span>
              {outboundRecords.map((out, idx) => {
                const isFailed =
                  out.status === 'FAILED' ||
                  (out.responseStatusCode != null && out.responseStatusCode >= 400);
                const isDelivered = out.status === 'DELIVERED' || out.responseStatusCode === 200;
                const targetName = out.appId.replace(/[_-]/g, ' ').toUpperCase();
                return (
                  <button
                    key={out.id || idx}
                    type="button"
                    onClick={() => setSelectedOutboundIndex(idx)}
                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border transition-all ${
                      selectedOutboundIndex === idx
                        ? 'bg-card border-primary text-foreground shadow-xs ring-1 ring-primary/20'
                        : 'bg-muted/40 border-border/50 text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    {isFailed ? (
                      <AlertTriangle className="h-3 w-3 text-destructive" />
                    ) : isDelivered ? (
                      <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                    ) : (
                      <Clock className="h-3 w-3 text-muted-foreground" />
                    )}
                    <span>{targetName}</span>
                    {out.responseStatusCode && (
                      <span
                        className={`text-[10px] font-mono ${
                          isFailed ? 'text-destructive font-bold' : 'text-muted-foreground'
                        }`}
                      >
                        {out.responseStatusCode}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}

          {activeOutbound ? (
            <div className="space-y-4 text-xs">
              <div className="p-3.5 rounded-xl bg-muted/20 border border-border/40 text-xs">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-x-6 gap-y-2.5">
                  <div className="grid grid-cols-[130px_1fr] items-center gap-2">
                    <span className="text-muted-foreground font-medium">Target App</span>
                    <span className="font-semibold text-foreground truncate">
                      {activeOutbound.appId.replace(/[_-]/g, ' ').toUpperCase()}
                    </span>
                  </div>
                  <div className="grid grid-cols-[130px_1fr] items-center gap-2">
                    <span className="text-muted-foreground font-medium">Endpoint URL</span>
                    <span
                      className="font-mono text-[11px] text-foreground truncate"
                      title={activeOutbound.targetUrl}
                    >
                      {activeOutbound.targetUrl}
                    </span>
                  </div>
                  <div className="grid grid-cols-[130px_1fr] items-center gap-2">
                    <span className="text-muted-foreground font-medium">Latency</span>
                    <span className="font-mono text-foreground truncate">
                      {activeOutbound.durationMs != null ? `${activeOutbound.durationMs}ms` : '—'}
                    </span>
                  </div>
                </div>
              </div>

              {isActiveOutboundFailed && activeOutbound.errorMessage && (
                <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-xs space-y-1">
                  <div className="font-semibold text-xs flex items-center gap-1.5">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                    <span>Target Delivery Error</span>
                  </div>
                  <div className="font-mono text-[11px] break-words pl-5">
                    {activeOutbound.errorMessage}
                  </div>
                </div>
              )}

              {/* ── 2-Column Split: Outbound Request vs Outbound Response ── */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* ── LEFT: Outbound Request ── */}
                <div className="rounded-xl border border-border bg-card p-3.5 space-y-3">
                  <div className="flex items-center justify-between pb-2 border-b border-border/60">
                    <div className="flex items-center gap-1.5">
                      <span className="font-bold text-foreground text-xs uppercase tracking-wide">
                        Request
                      </span>
                      <span className="font-mono text-[10px] px-1.5 py-0.2 rounded bg-muted">
                        {activeOutbound.httpMethod || 'POST'}
                      </span>
                      <span className="font-mono text-[10px] text-muted-foreground">
                        ({formatBytesCompact(activeOutbound.requestSizeBytes)})
                      </span>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="xs"
                      onClick={() =>
                        handleCopy(
                          JSON.stringify(
                            activeOutbound.requestBody ?? {
                              url: activeOutbound.targetUrl,
                              method: activeOutbound.httpMethod,
                              headers: activeOutbound.requestHeaders,
                              sizeBytes: activeOutbound.requestSizeBytes,
                            },
                            null,
                            2,
                          ),
                          'outboundRequest',
                        )
                      }
                      className="gap-1 text-xs h-6 px-2"
                    >
                      <Copy className="h-3 w-3" />
                      <span>{copied === 'outboundRequest' ? 'Copied' : 'Copy'}</span>
                    </Button>
                  </div>

                  {/* Outbound Request Headers */}
                  <div className="space-y-1">
                    <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
                      Request Headers
                    </span>
                    <div className="p-2.5 rounded-lg bg-muted/30 border border-border/60 font-mono text-[11px] max-h-32 overflow-auto space-y-0.5">
                      {Object.entries(activeOutbound.requestHeaders || {}).length > 0 ? (
                        Object.entries(activeOutbound.requestHeaders || {}).map(([key, val]) => (
                          <div key={key} className="flex justify-between gap-2">
                            <span className="text-cyan-600 dark:text-cyan-400 font-semibold truncate">
                              {key}:
                            </span>
                            <span className="text-muted-foreground truncate">{String(val)}</span>
                          </div>
                        ))
                      ) : (
                        <div className="text-muted-foreground italic font-sans text-[11px]">
                          Standard Application/JSON HTTP headers
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Outbound Request */}
                  <div className="space-y-1">
                    <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
                      Request
                    </span>
                    <pre className="text-xs font-mono bg-muted/40 p-3 rounded-lg border border-border/60 text-foreground leading-relaxed max-h-60 overflow-auto">
                      {JSON.stringify(
                        activeOutbound.requestBody ?? {
                          url: activeOutbound.targetUrl,
                          method: activeOutbound.httpMethod,
                          headers: activeOutbound.requestHeaders,
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </div>
                </div>

                {/* ── RIGHT: Outbound Response ── */}
                <div className="rounded-xl border border-border bg-card p-3.5 space-y-3">
                  <div className="flex items-center justify-between pb-2 border-b border-border/60">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-foreground text-xs uppercase tracking-wide">
                        Response
                      </span>
                      <StatusBadge
                        label={
                          activeOutbound.responseStatusCode
                            ? `HTTP ${activeOutbound.responseStatusCode}`
                            : activeOutbound.status
                        }
                        tone={
                          isActiveOutboundFailed
                            ? StatusTone.CRITICAL
                            : isActiveOutboundDelivered
                              ? StatusTone.HEALTHY
                              : StatusTone.NEUTRAL
                        }
                      />
                      {activeOutbound.durationMs != null && (
                        <span className="font-mono text-[11px] text-muted-foreground">
                          {activeOutbound.durationMs}ms
                        </span>
                      )}
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="xs"
                      onClick={() =>
                        handleCopy(
                          JSON.stringify(
                            activeOutbound.responseBody ?? {
                              statusCode: activeOutbound.responseStatusCode,
                              status: activeOutbound.status,
                              errorMessage: activeOutbound.errorMessage,
                              headers: activeOutbound.responseHeaders,
                            },
                            null,
                            2,
                          ),
                          'targetResponse',
                        )
                      }
                      className="gap-1 text-xs h-6 px-2"
                    >
                      <Copy className="h-3 w-3" />
                      <span>{copied === 'targetResponse' ? 'Copied' : 'Copy'}</span>
                    </Button>
                  </div>

                  {/* Outbound Response Headers */}
                  <div className="space-y-1">
                    <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
                      Response Headers
                    </span>
                    <div className="p-2.5 rounded-lg bg-muted/30 border border-border/60 font-mono text-[11px] max-h-32 overflow-auto space-y-0.5">
                      {Object.entries(activeOutbound.responseHeaders || {}).length > 0 ? (
                        Object.entries(activeOutbound.responseHeaders || {}).map(([key, val]) => (
                          <div key={key} className="flex justify-between gap-2">
                            <span className="text-emerald-600 dark:text-emerald-400 font-semibold truncate">
                              {key}:
                            </span>
                            <span className="text-muted-foreground truncate">{String(val)}</span>
                          </div>
                        ))
                      ) : (
                        <div className="text-muted-foreground italic font-sans text-[11px]">
                          Target server returned standard HTTP response headers
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Outbound Response */}
                  <div className="space-y-1">
                    <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
                      Response
                    </span>
                    <pre className="text-xs font-mono bg-muted/40 p-3 rounded-lg border border-border/60 text-foreground leading-relaxed max-h-60 overflow-auto">
                      {JSON.stringify(
                        activeOutbound.responseBody ?? {
                          statusCode: activeOutbound.responseStatusCode,
                          status: activeOutbound.status,
                          errorMessage: activeOutbound.errorMessage,
                          headers: activeOutbound.responseHeaders,
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="py-6 text-center text-xs text-muted-foreground">
              No outbound delivery record dispatched yet.
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

// Deprecated alias for backward-compatibility during phase transition
export {
  RecordDetail as RecordDetailInlineExpansion,
  type RecordDetailProps as RecordDetailInlineExpansionProps,
};
