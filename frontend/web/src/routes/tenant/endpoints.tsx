import { createRoute } from '@tanstack/react-router'
import { Route as appRoute } from '../tenant'
import { EndpointsTable } from '@/features/endpoints/components/EndpointsTable'
import { CreateWebhookEndpointModal } from '@/features/endpoints/components/CreateWebhookEndpointModal'
import { useTenantEndpointsQuery } from '@/features/endpoints/api/endpointsHooks'
import { Network } from 'lucide-react'

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/endpoints',
  component: EndpointsPage,
})

function EndpointsPage() {
  const { data: endpoints = [], isLoading } = useTenantEndpointsQuery()

  return (
    <div className="flex flex-col gap-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex flex-col gap-6">
        <div className="flex justify-between items-start">
          <div>
            <h2 className="text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-3">
              <Network className="w-8 h-8 text-indigo-600" />
              System Endpoints
            </h2>
          </div>
          <div className="flex-shrink-0">
            <CreateWebhookEndpointModal />
          </div>
        </div>
        <p className="text-slate-500 text-lg max-w-2xl">
          Configure Webhook and REST endpoints for routing data to and from your internal systems, such as an ERP or WMS.
        </p>
      </div>

      <div className="bg-white rounded-2xl shadow-sm border border-slate-200/60 p-6">
        <div className="mb-6">
          <h3 className="text-lg font-bold text-slate-900 mb-1">Configured Endpoints</h3>
          <p className="text-sm text-slate-500">
            Manage your internal system connections.
          </p>
        </div>

        <EndpointsTable data={endpoints} isLoading={isLoading} />
      </div>
    </div>
  )
}
