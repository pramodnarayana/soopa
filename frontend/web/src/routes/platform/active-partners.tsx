import { createFileRoute } from '@tanstack/react-router'
import { PartnersTable } from '@/features/partners/components/PartnersTable'
import { usePlatformPartners } from '@/features/partners/context/PlatformPartnersContext'
import { Server } from 'lucide-react'

export const Route = createFileRoute('/platform/active-partners')({
  component: ActivePartnersPage,
})

function ActivePartnersPage() {
  const { partners, isLoading } = usePlatformPartners();

  return (
    <div className="p-8">
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-2 bg-indigo-50 text-indigo-600 rounded-lg">
            <Server className="w-5 h-5" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Active Trading Partners</h1>
        </div>
        <p className="text-slate-500 max-w-2xl text-sm">
          Manage all active trading partners provisioned on the global platform. These partners are available for configuration in AS2 partnerships.
        </p>
      </div>
      <PartnersTable data={partners} isLoading={isLoading} scope="platform" />
    </div>
  )
}
