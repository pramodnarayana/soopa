import { createFileRoute } from '@tanstack/react-router'
import { PartnersTable } from '@/features/partners/components/PartnersTable'
import { usePlatformPartners } from '@/features/partners/context/PlatformPartnersContext'
import { Server } from 'lucide-react'
import { CreatePartnerModal } from '@/features/partners/components/CreatePartnerModal'
import { PlatformPartnersProvider } from '@/features/partners/context/PlatformPartnersContext'

export const Route = createFileRoute('/platform/partners')({
  component: () => (
    <PlatformPartnersProvider>
      <TradingPartnersPage />
    </PlatformPartnersProvider>
  )
})

export function TradingPartnersPage() {
  const { partners, isLoading } = usePlatformPartners();

  const localPartners = partners.filter(p => p.is_local);
  const remotePartners = partners.filter(p => !p.is_local);

  return (
    <div className="p-8">
      <div className="mb-8 flex items-center justify-between">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-2 bg-indigo-50 text-indigo-600 rounded-lg">
            <Server className="w-5 h-5" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Trading Partners</h1>
        </div>
        <CreatePartnerModal existingAs2Ids={partners.map(p => p.as2_id).filter(Boolean) as string[]} />
      </div>

      {partners.length === 0 && !isLoading ? (
        <PartnersTable data={[]} isLoading={false} scope="platform" />
      ) : (
        <div className="space-y-8">
          {localPartners.length > 0 && (
            <section>
              <h2 className="text-xl font-semibold text-slate-800 mb-4 px-2">Local Stations</h2>
              <PartnersTable data={localPartners} isLoading={isLoading} scope="platform" />
            </section>
          )}

          {remotePartners.length > 0 && (
            <section>
              <h2 className="text-xl font-semibold text-slate-800 mb-4 px-2">Remote Stations</h2>
              <PartnersTable data={remotePartners} isLoading={isLoading} scope="platform" />
            </section>
          )}
        </div>
      )}
    </div>
  )
}
