import { buttonVariants } from '@soopa/ui/components/ui/button';
import { createRoute, Link } from '@tanstack/react-router';
import { ArrowLeftRight, ArrowRight, Database, FileJson } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { CodeViewer } from '../../../components/ui/code-viewer';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../../components/ui/tabs';
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

// ─── Direction filter bar ─────────────────────────────────────────────────────

function DirectionFilter({
  value,
  onChange,
}: {
  value: Direction;
  onChange: (v: Direction) => void;
}) {
  const options: Direction[] = ['ALL', 'INBOUND', 'OUTBOUND'];
  return (
    <div className="flex gap-1 bg-slate-100 rounded-lg p-1">
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          onClick={() => onChange(opt)}
          className={`px-4 py-1.5 rounded-md text-xs font-semibold transition-all duration-150 ${
            value === opt
              ? 'bg-white shadow-sm text-indigo-700 border border-slate-200/80'
              : 'text-slate-500 hover:text-slate-800'
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
  const [activeTab, setActiveTab] = useState<'messages' | 'json'>('messages');
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
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex flex-col sm:flex-row gap-4 justify-between items-start sm:items-center">
        <div>
          <div className="flex items-center gap-2.5 mb-1">
            <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center">
              <ArrowLeftRight className="w-4 h-4 text-indigo-600" />
            </div>
            <h2 className="text-2xl font-bold tracking-tight text-slate-900">Transactions</h2>
          </div>
          <p className="text-slate-500 text-sm">
            Operational view of all EDI messages and their parsed JSON records.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <DirectionFilter value={direction} onChange={handleDirectionChange} />
        </div>
      </div>

      {/* Tabs */}
      <Tabs
        value={activeTab}
        onValueChange={(v) => setActiveTab(v as 'messages' | 'json')}
        className="space-y-6"
      >
        <TabsList className="bg-slate-100/50 p-1 rounded-lg border border-slate-200">
          <TabsTrigger
            value="messages"
            className="rounded-md data-[state=active]:bg-white data-[state=active]:shadow-sm px-4"
          >
            <div className="flex items-center gap-2">
              <Database className="w-4 h-4" />
              <span>EDI Messages</span>
              {accumulatedMessages.length > 0 && (
                <span className="ml-1 bg-indigo-100 text-indigo-700 text-xs font-bold px-1.5 py-0.5 rounded-full">
                  {accumulatedMessages.length}
                </span>
              )}
            </div>
          </TabsTrigger>
          <TabsTrigger
            value="json"
            className="rounded-md data-[state=active]:bg-white data-[state=active]:shadow-sm px-4"
          >
            <div className="flex items-center gap-2">
              <FileJson className="w-4 h-4" />
              <span>EDI JSON</span>
              {accumulatedJson.length > 0 && (
                <span className="ml-1 bg-indigo-100 text-indigo-700 text-xs font-bold px-1.5 py-0.5 rounded-full">
                  {accumulatedJson.length}
                </span>
              )}
            </div>
          </TabsTrigger>
        </TabsList>

        {/* EDI Messages Tab */}
        <TabsContent value="messages" className="focus:outline-none">
          <TransactionsTable<TransactionListItem>
            columns={SHARED_COLUMNS}
            data={accumulatedMessages}
            isLoading={messagesLoading && messagesOffset === 0}
            renderExpanded={(item) => <EdiMessageExpandedRow item={item} />}
            onLoadMore={() => setMessagesOffset((p) => p + LIMIT)}
            hasMore={(messagesData?.items.length ?? 0) === LIMIT}
            renderAction={(item) =>
              item.trace_id ? (
                onTraceClick ? (
                  <button
                    type="button"
                    onClick={() => onTraceClick(item.trace_id as string)}
                    className={buttonVariants({ variant: 'secondary', size: 'sm' })}
                    title="View Trace Timeline"
                  >
                    Trace
                    <ArrowRight className="h-3.5 w-3.5 ml-1" />
                  </button>
                ) : (
                  <Link
                    to={'/tenant/transactions/$traceId'}
                    params={{ traceId: item.trace_id }}
                    className={buttonVariants({ variant: 'secondary', size: 'sm' })}
                    title="View Trace Timeline"
                  >
                    Trace
                    <ArrowRight className="h-3.5 w-3.5 ml-1" />
                  </Link>
                )
              ) : null
            }
          />
        </TabsContent>

        {/* EDI JSON Tab */}
        <TabsContent value="json" className="focus:outline-none">
          <TransactionsTable<ExplorerEdiJson>
            columns={SHARED_COLUMNS}
            data={accumulatedJson}
            isLoading={jsonLoading && jsonOffset === 0}
            renderExpanded={(item) => <EdiJsonExpandedRow item={item} />}
            onLoadMore={() => setJsonOffset((p) => p + LIMIT)}
            hasMore={(jsonData?.items.length ?? 0) === LIMIT}
            renderAction={(item) =>
              item.trace_id ? (
                onTraceClick ? (
                  <button
                    type="button"
                    onClick={() => onTraceClick(item.trace_id as string)}
                    className={buttonVariants({ variant: 'secondary', size: 'sm' })}
                    title="View Trace Timeline"
                  >
                    Trace
                    <ArrowRight className="h-3.5 w-3.5 ml-1" />
                  </button>
                ) : (
                  <Link
                    to={'/tenant/transactions/$traceId'}
                    params={{ traceId: item.trace_id }}
                    className={buttonVariants({ variant: 'secondary', size: 'sm' })}
                    title="View Trace Timeline"
                  >
                    Trace
                    <ArrowRight className="h-3.5 w-3.5 ml-1" />
                  </Link>
                )
              ) : null
            }
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
