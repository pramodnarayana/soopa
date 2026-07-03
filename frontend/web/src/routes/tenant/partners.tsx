import { createRoute } from '@tanstack/react-router'
import { Route as appRoute } from '../tenant'
import { usePartners } from '@/features/partners/context/PartnersContext'
import { useDashboardData } from '@/features/dashboard/api/useDashboardData'
import { PartnersTable } from '@/features/partners/components/PartnersTable'
import { Server } from 'lucide-react'

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/partners',
  component: PartnersPage,
})

export function PartnersPage() {
  const { data: userProfile } = useDashboardData()
  const { partners, isLoading } = usePartners()

  return (
    <div className="flex flex-col gap-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out p-8">

      {/* Header */}
      <section className="flex flex-col gap-2 pb-6 border-b border-slate-200/60">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-2 bg-indigo-50 text-indigo-600 rounded-lg">
            <Server className="w-5 h-5" />
          </div>
          <h2 className="text-3xl md:text-4xl font-extrabold tracking-tight text-slate-900">
            Trading Partners
          </h2>
        </div>
        <p className="text-slate-500 text-lg max-w-2xl">
          Manage your configured {userProfile?.allow_private_as2 ? "AS2 and " : ""}SFTP integration partners.
        </p>
      </section>

      {/* Main Grid */}
      <div className="space-y-8">
        <PartnersTable data={partners} isLoading={isLoading} scope="tenant" />
      </div>

    </div>
  )
}
