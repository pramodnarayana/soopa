import { createRoute } from '@tanstack/react-router'
import { Route as appRoute } from '../tenant'
import { AS2PartnerCard } from '@/features/dashboard/components/AS2PartnerCard'
import { SFTPPartnerCard } from '@/features/dashboard/components/SFTPPartnerCard'
import { usePartners } from '@/features/partners/context/PartnersContext'
import { useDashboardData } from '@/features/dashboard/api/useDashboardData'

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/partners',
  component: PartnersPage,
})

function PartnersPage() {
  const { data: userProfile } = useDashboardData()
  const { partners, addPartner } = usePartners()
  const as2Count = partners.filter(p => p.type === 'AS2').length

  return (
    <div className="flex flex-col gap-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">

      {/* Header */}
      <section className="flex flex-col gap-2 pb-6 border-b border-slate-200/60">
        <h2 className="text-3xl md:text-4xl font-extrabold tracking-tight text-slate-900">
          Trading Partners
        </h2>
        <p className="text-slate-500 text-lg max-w-2xl">
          Manage your configured {userProfile?.allow_private_as2 ? "AS2 and " : ""}SFTP integration partners.
        </p>
      </section>

      {/* Main Grid */}
      <div className="grid gap-8 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
        {userProfile?.allow_private_as2 && (
          <div className="lg:col-span-1 xl:col-span-1">
            <AS2PartnerCard
              count={as2Count}
              onSave={(data) => {
                // The tenant context currently uses a simpler type, but we pass it anyway
                addPartner(data as any)
              }}
            />
          </div>
        )}
        <div className="lg:col-span-1 xl:col-span-1">
          <SFTPPartnerCard />
        </div>
      </div>

    </div>
  )
}
