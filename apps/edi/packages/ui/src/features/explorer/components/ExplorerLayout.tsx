import { useState, useEffect } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FileJson, Database } from 'lucide-react'
import { CodeViewer } from '@/components/ui/code-viewer'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { FilterBuilder } from './FilterBuilder'
import { ExplorerTable } from './ExplorerTable'
import { useExplorerEdiMessages, useExplorerEdiJson } from '../api/explorerApi'
import type { FilterRule } from '../types'

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
    render: (item: any) => item.created_at ? new Date(item.created_at).toLocaleString() : '-'
  },
]

const messageColumns = sharedColumns
const jsonColumns = sharedColumns

const availableFields = [
  { label: 'Trading Partner ID', value: 'trading_partner_id' },
  { label: 'Status', value: 'status' },
  { label: 'Direction', value: 'direction' },
  { label: 'Transaction Type', value: 'transaction_type' },
  { label: 'Sender ID', value: 'sender_id' },
  { label: 'Receiver ID', value: 'receiver_id' },
  { label: 'Shipment Number', value: 'business_metadata.shipment_id' },
  { label: 'Load Number', value: 'business_metadata.load_number' },
]

function ExplorerCommonFields({ item }: { item: any }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-6 mb-6">
      <div className="space-y-1.5">
        <Label className="text-xs text-slate-500">Transaction Type</Label>
        <Input readOnly value={item.transaction_type || '-'} className="font-mono text-sm bg-slate-50 border-slate-200 shadow-sm" />
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs text-slate-500">ISA Sender</Label>
        <Input readOnly value={item.sender_id || '-'} className="font-mono text-sm bg-slate-50 border-slate-200 shadow-sm" />
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs text-slate-500">ISA Receiver</Label>
        <Input readOnly value={item.receiver_id || '-'} className="font-mono text-sm bg-slate-50 border-slate-200 shadow-sm" />
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs text-slate-500">GS Sender</Label>
        <Input readOnly value={item.gs_sender_id || '-'} className="font-mono text-sm bg-slate-50 border-slate-200 shadow-sm" />
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs text-slate-500">GS Receiver</Label>
        <Input readOnly value={item.gs_receiver_id || '-'} className="font-mono text-sm bg-slate-50 border-slate-200 shadow-sm" />
      </div>
    </div>
  )
}

export function ExplorerLayout() {
  const [filters, setFilters] = useState<FilterRule[]>([])
  const [activeTab, setActiveTab] = useState('messages')
  const [messagesOffset, setMessagesOffset] = useState(0)
  const [jsonOffset, setJsonOffset] = useState(0)
  const limit = 100

  const [accumulatedMessages, setAccumulatedMessages] = useState<any[]>([])
  const [accumulatedJson, setAccumulatedJson] = useState<any[]>([])

  const { data: messagesData, isLoading: messagesLoading } = useExplorerEdiMessages(filters, limit, messagesOffset, activeTab === 'messages')
  const { data: jsonData, isLoading: jsonLoading } = useExplorerEdiJson(filters, limit, jsonOffset, activeTab === 'json')

  const handleFiltersChange = (newFilters: FilterRule[]) => {
    setFilters(newFilters)
    setMessagesOffset(0)
    setJsonOffset(0)
    setAccumulatedMessages([])
    setAccumulatedJson([])
  }

  useEffect(() => {
    if (messagesData?.items) {
      setAccumulatedMessages(prev => {
        if (messagesOffset === 0) return messagesData.items
        const nextMap = new Map(prev.map(i => [i.id, i]))
        messagesData.items.forEach((i: any) => nextMap.set(i.id, i))
        return Array.from(nextMap.values())
      })
    }
  }, [messagesData, messagesOffset])

  useEffect(() => {
    if (jsonData?.items) {
      setAccumulatedJson(prev => {
        if (jsonOffset === 0) return jsonData.items
        const nextMap = new Map(prev.map(i => [i.id, i]))
        jsonData.items.forEach((i: any) => nextMap.set(i.id, i))
        return Array.from(nextMap.values())
      })
    }
  }, [jsonData, jsonOffset])

  const handleMessagesLoadMore = () => setMessagesOffset(prev => prev + limit)
  const handleJsonLoadMore = () => setJsonOffset(prev => prev + limit)

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
          <TabsTrigger value="messages" className="rounded-md data-[state=active]:bg-white data-[state=active]:shadow-sm px-4">
            <div className="flex items-center gap-2">
              <Database className="w-4 h-4" />
              <span>EDI Messages</span>
            </div>
          </TabsTrigger>
          <TabsTrigger value="json" className="rounded-md data-[state=active]:bg-white data-[state=active]:shadow-sm px-4">
            <div className="flex items-center gap-2">
              <FileJson className="w-4 h-4" />
              <span>EDI JSON</span>
            </div>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="messages" className="focus:outline-none">
          <ExplorerTable
            columns={messageColumns}
            data={accumulatedMessages}
            isLoading={messagesLoading && messagesOffset === 0}
            headerToolbar={
              <FilterBuilder
                availableFields={availableFields}
                filters={filters}
                onChange={handleFiltersChange}
              />
            }
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
          <ExplorerTable
            columns={jsonColumns}
            data={accumulatedJson}
            isLoading={jsonLoading && jsonOffset === 0}
            headerToolbar={
              <FilterBuilder
                availableFields={availableFields}
                filters={filters}
                onChange={handleFiltersChange}
              />
            }
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
                    value={item.payload ? JSON.stringify(item.payload, null, 2) : 'No payload available.'}
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
  )
}
