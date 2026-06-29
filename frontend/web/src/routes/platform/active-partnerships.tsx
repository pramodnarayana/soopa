import { createFileRoute } from '@tanstack/react-router'
import { PartnershipsTable } from '@/features/partners/components/PartnershipsTable'
import { usePlatformPartners } from '@/features/partners/context/PlatformPartnersContext'
import { Network } from 'lucide-react'

export const Route = createFileRoute('/platform/active-partnerships')({
  component: ActivePartnershipsPage,
})

function ActivePartnershipsPage() {
  const { partnerships, isLoading } = usePlatformPartners();

  return (
    <div className="p-8">
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-2 bg-emerald-50 text-emerald-600 rounded-lg">
            <Network className="w-5 h-5" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Active AS2 Partnerships</h1>
        </div>
        <p className="text-slate-500 max-w-2xl text-sm">
          Manage all active AS2 communication channels between local and remote trading partners.
        </p>
      </div>
      <PartnershipsTable data={partnerships} isLoading={isLoading} scope="platform" />
    </div>
  )
}
