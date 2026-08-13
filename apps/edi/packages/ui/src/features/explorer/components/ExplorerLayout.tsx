import { Tabs, TabsContent, TabsList, TabsTrigger } from '@soopa/ui';
import { Input } from '@soopa/ui/components/ui/input';
import { Label } from '@soopa/ui/components/ui/label';
import { type FieldDef, QueryBuilder } from '@soopa/ui/components/ui/query-builder';
import { Database, FileJson } from 'lucide-react';
import { useEffect, useState } from 'react';
import { CodeViewer } from '../../../components/ui/code-viewer';
import { useExplorerEdiJson, useExplorerEdiMessages } from '../api/explorerApi';
import type { ExplorerEdiJson, ExplorerEdiMessage, FilterRule } from '../types';
import { ExplorerTable } from './ExplorerTable';

const sharedColumns = [
  { key: 'transaction_type', label: 'Type', className: 'w-[10%]' },
  { key: 'direction', label: 'Direction', className: 'w-[12%]' },
  { key: 'sender_id', label: 'Sender ID', className: 'w-[18%]' },
  { key: 'receiver_id', label: 'Receiver ID', className: 'w-[18%]' },
  { key: 'status', label: 'Status', className: 'w-[17%]' },
  {
    key: 'created_at',
    label: 'Created At',
    className: 'w-[25%]',
    render: (item: { created_at?: string | null }) =>
      item.created_at ? new Date(item.created_at).toLocaleString() : '-',
  },
];

const messageColumns = sharedColumns;
const jsonColumns = sharedColumns;

const messageFields: FieldDef[] = [
  {
    label: 'Trading Partner ID',
    id: 'trading_partner_id',
    type: 'text',
    operators: ['eq', 'neq', 'contains'],
  },
  { label: 'Status', id: 'status', type: 'text', operators: ['eq', 'neq', 'contains'] },
  { label: 'Direction', id: 'direction', type: 'text', operators: ['eq', 'neq', 'contains'] },
  {
    label: 'Transaction Type',
    id: 'transaction_type',
    type: 'text',
    operators: ['eq', 'neq', 'contains'],
  },
  { label: 'Sender ID', id: 'sender_id', type: 'text', operators: ['eq', 'neq', 'contains'] },
  {
    label: 'Receiver ID',
    id: 'receiver_id',
    type: 'text',
    operators: ['eq', 'neq', 'contains'],
  },
];

const jsonFields: FieldDef[] = [
  {
    label: 'Trading Partner ID',
    id: 'trading_partner_id',
    type: 'text',
    operators: ['eq', 'neq', 'contains'],
  },
  { label: 'Status', id: 'status', type: 'text', operators: ['eq', 'neq', 'contains'] },
  { label: 'Direction', id: 'direction', type: 'text', operators: ['eq', 'neq', 'contains'] },
  {
    label: 'Transaction Type',
    id: 'transaction_type',
    type: 'text',
    operators: ['eq', 'neq', 'contains'],
  },
  { label: 'Sender ID', id: 'sender_id', type: 'text', operators: ['eq', 'neq', 'contains'] },
  {
    label: 'Receiver ID',
    id: 'receiver_id',
    type: 'text',
    operators: ['eq', 'neq', 'contains'],
  },
  {
    label: 'Shipment Number',
    id: 'business_metadata.shipment_id',
    type: 'text',
    operators: ['eq', 'neq', 'contains'],
  },
  {
    label: 'Load Number',
    id: 'business_metadata.load_number',
    type: 'text',
    operators: ['eq', 'neq', 'contains'],
  },
];

function ExplorerCommonFields({
  item,
}: {
  item: Partial<ExplorerEdiMessage> & Partial<ExplorerEdiJson>;
}) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-6 mb-6">
      <div className="space-y-1.5">
        <Label className="text-xs text-slate-500">Transaction Type</Label>
        <Input
          readOnly
          value={item.transaction_type || '-'}
          className="font-mono text-sm bg-slate-50 border-slate-200 shadow-sm"
        />
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs text-slate-500">ISA Sender</Label>
        <Input
          readOnly
          value={item.sender_id || '-'}
          className="font-mono text-sm bg-slate-50 border-slate-200 shadow-sm"
        />
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs text-slate-500">ISA Receiver</Label>
        <Input
          readOnly
          value={item.receiver_id || '-'}
          className="font-mono text-sm bg-slate-50 border-slate-200 shadow-sm"
        />
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs text-slate-500">GS Sender</Label>
        <Input
          readOnly
          value={item.gs_sender_id || '-'}
          className="font-mono text-sm bg-slate-50 border-slate-200 shadow-sm"
        />
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs text-slate-500">GS Receiver</Label>
        <Input
          readOnly
          value={item.gs_receiver_id || '-'}
          className="font-mono text-sm bg-slate-50 border-slate-200 shadow-sm"
        />
      </div>
    </div>
  );
}

export function ExplorerLayout() {
  const [messagesFilters, setMessagesFilters] = useState<FilterRule[]>([]);
  const [jsonFilters, setJsonFilters] = useState<FilterRule[]>([]);
  const [activeTab, setActiveTab] = useState('messages');
  const [messagesOffset, setMessagesOffset] = useState(0);
  const [jsonOffset, setJsonOffset] = useState(0);
  const limit = 100;

  const [accumulatedMessages, setAccumulatedMessages] = useState<ExplorerEdiMessage[]>([]);
  const [accumulatedJson, setAccumulatedJson] = useState<ExplorerEdiJson[]>([]);

  const { data: messagesData, isLoading: messagesLoading } = useExplorerEdiMessages(
    messagesFilters,
    limit,
    messagesOffset,
    activeTab === 'messages',
  );
  const { data: jsonData, isLoading: jsonLoading } = useExplorerEdiJson(
    jsonFilters,
    limit,
    jsonOffset,
    activeTab === 'json',
  );

  const handleMessagesFiltersChange = (newFilters: FilterRule[]) => {
    // Retain only supported operators
    const supportedOperators = new Set(['eq', 'neq', 'contains']);
    const normalizedFilters = newFilters.filter((rule) => supportedOperators.has(rule.operator));
    setMessagesFilters(normalizedFilters);
    setMessagesOffset(0);
    setAccumulatedMessages([]);
  };

  const handleJsonFiltersChange = (newFilters: FilterRule[]) => {
    // Retain only supported operators
    const supportedOperators = new Set(['eq', 'neq', 'contains']);
    const normalizedFilters = newFilters.filter((rule) => supportedOperators.has(rule.operator));
    setJsonFilters(normalizedFilters);
    setJsonOffset(0);
    setAccumulatedJson([]);
  };

  useEffect(() => {
    if (messagesData?.items) {
      setAccumulatedMessages((prev) => {
        if (messagesOffset === 0) return messagesData.items;
        const nextMap = new Map(prev.map((i) => [i.id, i]));
        messagesData.items.forEach((i: ExplorerEdiMessage) => nextMap.set(i.id, i));
        return Array.from(nextMap.values());
      });
    }
  }, [messagesData, messagesOffset]);

  useEffect(() => {
    if (jsonData?.items) {
      setAccumulatedJson((prev) => {
        if (jsonOffset === 0) return jsonData.items;
        const nextMap = new Map(prev.map((i) => [i.id, i]));
        jsonData.items.forEach((i: ExplorerEdiJson) => nextMap.set(i.id, i));
        return Array.from(nextMap.values());
      });
    }
  }, [jsonData, jsonOffset]);

  const handleMessagesLoadMore = () => setMessagesOffset((prev) => prev + limit);
  const handleJsonLoadMore = () => setJsonOffset((prev) => prev + limit);

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row gap-4 justify-between items-start sm:items-center mb-2">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-slate-900">Data Explorer</h2>
          <p className="text-slate-500 text-sm mt-1">Raw table queries with advanced filtering.</p>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <TabsList className="bg-slate-100/50 p-1 rounded-lg border border-slate-200">
          <TabsTrigger
            value="messages"
            className="rounded-md data-[state=active]:bg-white data-[state=active]:shadow-sm px-4"
          >
            <div className="flex items-center gap-2">
              <Database className="w-4 h-4" />
              <span>EDI Messages</span>
            </div>
          </TabsTrigger>
          <TabsTrigger
            value="json"
            className="rounded-md data-[state=active]:bg-white data-[state=active]:shadow-sm px-4"
          >
            <div className="flex items-center gap-2">
              <FileJson className="w-4 h-4" />
              <span>EDI JSON</span>
            </div>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="messages" className="focus:outline-none">
          <div className="mb-4 flex justify-end">
            <QueryBuilder
              fields={messageFields}
              rules={messagesFilters as any}
              onChange={(f) => handleMessagesFiltersChange(f as FilterRule[])}
            />
          </div>
          <ExplorerTable
            columns={messageColumns}
            data={accumulatedMessages}
            isLoading={messagesLoading && messagesOffset === 0}
            renderExpanded={(item) => (
              <div className="space-y-4">
                <ExplorerCommonFields item={item} />
                <div>
                  <h4 className="text-sm font-semibold text-slate-900 mb-2">Raw Payload</h4>
                  <CodeViewer
                    height={400}
                    language="edi"
                    value={item.edi_data || item.storage_uri || 'No payload available.'}
                  />
                </div>
              </div>
            )}
            onLoadMore={handleMessagesLoadMore}
            hasMore={messagesData?.items.length === limit}
          />
        </TabsContent>

        <TabsContent value="json" className="focus:outline-none">
          <div className="mb-4 flex justify-end">
            <QueryBuilder
              fields={jsonFields}
              rules={jsonFilters as any}
              onChange={(f) => handleJsonFiltersChange(f as FilterRule[])}
            />
          </div>
          <ExplorerTable
            columns={jsonColumns}
            data={accumulatedJson}
            isLoading={jsonLoading && jsonOffset === 0}
            renderExpanded={(item) => (
              <div className="space-y-4">
                <ExplorerCommonFields item={item} />
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <h4 className="text-sm font-semibold text-slate-700 mb-2">Business Metadata</h4>
                    <CodeViewer
                      height={400}
                      language="json"
                      value={JSON.stringify(item.business_metadata || {}, null, 2)}
                    />
                  </div>
                  <div>
                    <h4 className="text-sm font-semibold text-slate-700 mb-2">JSON Payload</h4>
                    <CodeViewer
                      height={400}
                      language="json"
                      value={
                        item.payload
                          ? JSON.stringify(item.payload, null, 2)
                          : 'No payload available.'
                      }
                    />
                  </div>
                </div>
              </div>
            )}
            onLoadMore={handleJsonLoadMore}
            hasMore={jsonData?.items.length === limit}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
