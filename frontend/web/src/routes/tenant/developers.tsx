import { createRoute } from '@tanstack/react-router'
import { Route as appRoute } from '../tenant'
import { Terminal } from 'lucide-react'
import { ApiTokensTable } from '@/features/developers/components/ApiTokensTable'
import { CreateApiTokenModal } from '@/features/developers/components/CreateApiTokenModal'
import { useApiTokensQuery } from '@/features/developers/api/apiTokenHooks'

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/developers',
  component: DevelopersPage,
})

export function DevelopersPage() {
  const { data, isLoading } = useApiTokensQuery()

  const tokens = data?.tokens ?? []

  return (
    <div className="flex flex-col gap-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out p-8">

      {/* Header */}
      <section className="flex flex-col gap-2 pb-6 border-b border-slate-200/60">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 mb-2">
            <h2 className="text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-3">
              <Terminal className="w-8 h-8 text-indigo-600" />
              API Access
            </h2>
          </div>
          <div className="flex-shrink-0">
            <CreateApiTokenModal />
          </div>
        </div>
      </section>

      {/* Main Grid */}
      <div className="space-y-8">
        <ApiTokensTable data={tokens} isLoading={isLoading} />
      </div>

    </div>
  )
}
