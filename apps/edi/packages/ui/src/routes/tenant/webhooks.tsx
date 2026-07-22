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

export function WebhooksPage() {
  const { data: webhooks = [], isLoading } = useTenantWebhooksQuery()

  return (
    <div className="flex flex-col gap-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out p-8">
      {/* Header */}
      <section className="flex flex-col gap-2 pb-6 border-b border-slate-200/60">
        <div className="flex justify-between items-center">
          <div className="flex items-center gap-3 mb-2">
            <h2 className="text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-3">
              <Network className="w-8 h-8 text-indigo-600" />
              Webhooks
            </h2>
          </div>
          <div className="flex-shrink-0">
            <CreateWebhookModal />
          </div>
        </div>
      </section>

      {/* Main Grid */}
      <div className="space-y-8">
        <WebhooksTable data={webhooks} isLoading={isLoading} />
      </div>
    </div>
  )
}
