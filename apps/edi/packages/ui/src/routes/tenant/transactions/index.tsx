import { buttonVariants } from '@soopa/ui/components/ui/button';
import { createRoute, Link } from '@tanstack/react-router';
import { ArrowRight, Database, FileJson } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { CodeViewer } from '../../../components/ui/code-viewer';
import { useExplorerEdiJson } from '../../../features/explorer/api/explorerApi';
import type { ExplorerEdiJson } from '../../../features/explorer/types';
import { useTransactions } from '../../../features/transactions/api/transactionsApi';
import { TransactionsTable } from '../../../features/transactions/components/TransactionsTable';
import type { TransactionListItem } from '../../../features/transactions/types';
import { Route as appRoute } from '../../tenant';

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/transactions',
  component: TransactionsPage,
});

// ─── Types ────────────────────────────────────────────────────────────────────

type Direction = 'ALL' | 'INBOUND' | 'OUTBOUND';

// ─── Shared trace action component ───────────────────────────────────────────

function TraceAction({
  traceId,
  onTraceClick,
}: {
  traceId: string;
  onTraceClick?: (traceId: string) => void;
}) {
  if (onTraceClick) {
    return (
      <button
        type="button"
        onClick={() => onTraceClick(traceId)}
        className={buttonVariants({ variant: 'secondary', size: 'sm' })}
        title="View Trace Timeline"
      >
        Trace
        <ArrowRight className="h-3.5 w-3.5 ml-1" />
      </button>
    );
  }
  return (
    <Link
      to={'/tenant/transactions/$traceId'}
      params={{ traceId }}
      className={buttonVariants({ variant: 'secondary', size: 'sm' })}
      title="View Trace Timeline"
    >
      Trace
      <ArrowRight className="h-3.5 w-3.5 ml-1" />
    </Link>
  );
}

// ─── Shared field renderers ───────────────────────────────────────────────────

function FieldGrid({ items }: { items: { label: string; value: string | null | undefined }[] }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {items.map(({ label, value }) => (
        <div key={label} className="bg-white rounded-lg border border-slate-200 p-3 shadow-sm">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
            {label}
          </div>
          <div className="font-mono text-sm text-slate-900 truncate">{value || '—'}</div>
        </div>
      ))}
    </div>
  );
}

// ─── EDI Message expand row ───────────────────────────────────────────────────

function EdiMessageExpandedRow({ item }: { item: TransactionListItem }) {
  return (
    <div className="space-y-4">
      <FieldGrid
        items={[
          { label: 'ISA Sender', value: item.sender_id },
          { label: 'ISA Receiver', value: item.receiver_id },
          { label: 'Transaction Type', value: item.transaction_type },
          { label: 'Status', value: item.status },
        ]}
      />
      <div className="mt-4">
        <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
          Raw EDI Data
        </div>
        <CodeViewer language="edi" height={350} value={item.edi_data || 'No EDI data available.'} />
      </div>
    </div>
  );
}

// ─── EDI JSON expand row ─────────────────────────────────────────────────────

function EdiJsonExpandedRow({ item }: { item: ExplorerEdiJson }) {
  return (
    <div className="space-y-4">
      <FieldGrid
        items={[
          { label: 'ISA Sender', value: item.sender_id },
          { label: 'ISA Receiver', value: item.receiver_id },
          { label: 'GS Sender', value: item.gs_sender_id },
          { label: 'GS Receiver', value: item.gs_receiver_id },
        ]}
      />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
            Business Metadata
          </div>
          <CodeViewer
            language="json"
            height={350}
            value={JSON.stringify(item.business_metadata ?? {}, null, 2)}
          />
        </div>
        <div>
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
            JSON Payload
          </div>
          <CodeViewer
            language="json"
            height={350}
            value={item.payload ? JSON.stringify(item.payload, null, 2) : 'No payload available.'}
          />
        </div>
      </div>
    </div>
  );
}

// ─── Column definitions ───────────────────────────────────────────────────────

const SHARED_COLUMNS = [
  { key: 'direction', label: 'Direction', className: 'w-[14%]' },
  { key: 'transaction_type', label: 'Type', className: 'w-[10%]' },
  { key: 'sender_id', label: 'Sender ID', className: 'w-[20%]' },
  { key: 'receiver_id', label: 'Receiver ID', className: 'w-[20%]' },
  { key: 'status', label: 'Status', className: 'w-[16%]' },
  {
    key: 'created_at',
    label: 'Created At',
    className: 'w-[20%]',
    render: (item: { created_at?: string | null }) =>
      item.created_at ? (
        <span className="text-slate-600 text-xs">{new Date(item.created_at).toLocaleString()}</span>
      ) : (
        <span className="text-slate-400">—</span>
      ),
  },
];

// ─── Types ───────────────────────────────────────────────────────────────────

type ActiveTab = 'messages' | 'json';

// ─── Direction filter ─────────────────────────────────────────────────────────

function DirectionFilter({
  value,
  onChange,
}: {
  value: Direction;
  onChange: (v: Direction) => void;
}) {
  const options: Direction[] = ['ALL', 'INBOUND', 'OUTBOUND'];
  return (
    <div className="flex gap-1 bg-muted p-1 rounded-lg border border-border/40" role="group" aria-label="Filter by direction">
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          onClick={() => onChange(opt)}
          aria-pressed={value === opt}
          className={`px-4 py-1.5 rounded-md text-xs font-semibold transition-all duration-150 ${
            value === opt
              ? 'bg-background shadow-sm text-foreground border border-border/60'
              : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

const LIMIT = 50;

export function TransactionsPage({ onTraceClick }: { onTraceClick?: (traceId: string) => void }) {
  const [activeTab, setActiveTab] = useState<ActiveTab>('messages');
  const [direction, setDirection] = useState<Direction>('ALL');

  // EDI Messages (from transactions endpoint)
  const [messagesOffset, setMessagesOffset] = useState(0);
  const [accumulatedMessages, setAccumulatedMessages] = useState<TransactionListItem[]>([]);

  const { data: messagesData, isLoading: messagesLoading } = useTransactions({
    limit: LIMIT,
    offset: messagesOffset,
    direction: direction === 'ALL' ? undefined : direction,
  });

  useEffect(() => {
    if (messagesData?.items) {
      setAccumulatedMessages((prev) => {
        if (messagesOffset === 0) return messagesData.items;
        const map = new Map(prev.map((i) => [i.id, i]));
        messagesData.items.forEach((i) => map.set(i.id, i));
        return Array.from(map.values());
      });
    }
  }, [messagesData, messagesOffset]);

  // EDI JSON (from explorer endpoint with direction filter)
  const [jsonOffset, setJsonOffset] = useState(0);
  const [accumulatedJson, setAccumulatedJson] = useState<ExplorerEdiJson[]>([]);

  const jsonFilters = useMemo(
    () =>
      direction === 'ALL'
        ? []
        : [{ field: 'direction', operator: 'eq' as const, value: direction }],
    [direction],
  );

  const { data: jsonData, isLoading: jsonLoading } = useExplorerEdiJson(
    jsonFilters,
    LIMIT,
    jsonOffset,
    activeTab === 'json',
  );

  useEffect(() => {
    if (jsonData?.items) {
      setAccumulatedJson((prev) => {
        if (jsonOffset === 0) return jsonData.items;
        const map = new Map(prev.map((i) => [i.id, i]));
        jsonData.items.forEach((i) => map.set(i.id, i));
        return Array.from(map.values());
      });
    }
  }, [jsonData, jsonOffset]);

  // Reset pagination when direction changes
  const handleDirectionChange = (d: Direction) => {
    setDirection(d);
    setMessagesOffset(0);
    setJsonOffset(0);
    setAccumulatedMessages([]);
    setAccumulatedJson([]);
  };

  return (
    <div className="flex flex-col min-h-full animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">
      {/* Page Header */}
      <div className="bg-card border-b border-border shadow-[0_2px_8px_rgb(0,0,0,0.02)]">
        <div className="w-full pb-0">
          {/* Title row */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4">
            <div>
              <h2 className="text-3xl md:text-4xl font-extrabold tracking-tight text-foreground">
                Transactions
              </h2>
            </div>
            <DirectionFilter value={direction} onChange={handleDirectionChange} />
          </div>

          {/* Underline tab nav */}
          <nav className="flex items-center gap-8" role="tablist" aria-label="Transaction types">
            <button
              type="button"
              role="tab"
              onClick={() => setActiveTab('messages')}
              aria-selected={activeTab === 'messages'}
              aria-controls="messages-panel"
              data-status={activeTab === 'messages' ? 'active' : undefined}
              className="inline-flex items-center gap-2 pb-4 pt-2 border-b-[3px] font-semibold text-[15px] transition-colors border-transparent text-muted-foreground hover:text-foreground data-[status=active]:border-primary data-[status=active]:text-primary"
            >
              <Database className="w-4 h-4" />
              EDI Messages
            </button>
            <button
              type="button"
              role="tab"
              onClick={() => setActiveTab('json')}
              aria-selected={activeTab === 'json'}
              aria-controls="json-panel"
              data-status={activeTab === 'json' ? 'active' : undefined}
              className="inline-flex items-center gap-2 pb-4 pt-2 border-b-[3px] font-semibold text-[15px] transition-colors border-transparent text-muted-foreground hover:text-foreground data-[status=active]:border-primary data-[status=active]:text-primary"
            >
              <FileJson className="w-4 h-4" />
              EDI Json
            </button>
          </nav>
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 w-full pt-8">
        {activeTab === 'messages' ? (
          <div id="messages-panel" role="tabpanel" aria-labelledby="messages-tab">
            <TransactionsTable<TransactionListItem>
            columns={SHARED_COLUMNS}
            data={accumulatedMessages}
            isLoading={messagesLoading && messagesOffset === 0}
            renderExpanded={(item) => <EdiMessageExpandedRow item={item} />}
            onLoadMore={() => setMessagesOffset((p) => p + LIMIT)}
            hasMore={(messagesData?.items.length ?? 0) === LIMIT}
            renderAction={(item) =>
              item.trace_id ? (
                <TraceAction traceId={item.trace_id} onTraceClick={onTraceClick} />
              ) : null
            }
          />
          </div>
        ) : (
          <div id="json-panel" role="tabpanel" aria-labelledby="json-tab">
            <TransactionsTable<ExplorerEdiJson>
            columns={SHARED_COLUMNS}
            data={accumulatedJson}
            isLoading={jsonLoading && jsonOffset === 0}
            renderExpanded={(item) => <EdiJsonExpandedRow item={item} />}
            onLoadMore={() => setJsonOffset((p) => p + LIMIT)}
            hasMore={(jsonData?.items.length ?? 0) === LIMIT}
            renderAction={(item) =>
              item.trace_id ? (
                <TraceAction traceId={item.trace_id} onTraceClick={onTraceClick} />
              ) : null
            }
          />
          </div>
        )}
      </div>
    </div>
  );
}
