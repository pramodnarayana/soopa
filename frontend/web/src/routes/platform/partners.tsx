import { createFileRoute } from '@tanstack/react-router'
import { AS2PartnerCard } from '@/features/dashboard/components/AS2PartnerCard'
import { AS2PartnershipCard } from '@/features/dashboard/components/AS2PartnershipCard'
import { usePlatformPartners } from '@/features/partners/context/PlatformPartnersContext'

export const Route = createFileRoute('/platform/partners')({
  component: PlatformPartnersPage,
})

function PlatformPartnersPage() {
  const { partners, partnerships, addPartner, addPartnership } = usePlatformPartners()

  const as2Count = partners.filter(p => p.type === 'AS2').length
  const partnershipCount = partnerships.length

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-6">Trading Partners</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <AS2PartnerCard
          count={as2Count}
          onSave={addPartner}
        />
        <AS2PartnershipCard
          count={partnershipCount}
          availablePartners={partners}
          onSave={addPartnership}
        />
      </div>
    </div>
  )
}
