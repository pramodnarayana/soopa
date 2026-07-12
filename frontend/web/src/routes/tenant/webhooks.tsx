import { createRoute } from '@tanstack/react-router'
import { Route as appRoute } from '../tenant'
import { WebhooksTable } from '@/features/webhooks/components/WebhooksTable'
import { CreateWebhookModal } from '@/features/webhooks/components/CreateWebhookModal'
import { useTenantWebhooksQuery } from '@/features/webhooks/api/webhookHooks'
import { Network } from 'lucide-react'

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/webhooks',
  component: WebhooksPage,
})

function WebhooksPage() {
  const { data: webhooks = [], isLoading } = useTenantWebhooksQuery()

  return (
    <div className="flex flex-col gap-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex flex-col gap-6">
        <div className="flex justify-between items-start">
          <div>
            <h2 className="text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-3">
              <Network className="w-8 h-8 text-indigo-600" />
              Webhooks
            </h2>
          </div>
          <div className="flex-shrink-0">
            <CreateWebhookModal />
          </div>
        </div>
      </div>

      <div className="bg-white rounded-2xl shadow-sm border border-slate-200/60 p-6">
        <WebhooksTable data={webhooks} isLoading={isLoading} />
      </div>
    </div>
  )
}
