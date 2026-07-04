import { createRoute } from '@tanstack/react-router'
import { Route as appRoute } from '../tenant'
import { usePartners } from '@/features/partners/context/PartnersContext'
import { SftpPartnersTable } from '@/features/partners/components/SftpPartnersTable'
import { CreateSftpPartnerModal } from '@/features/partners/components/CreateSftpPartnerModal'
import { Users } from 'lucide-react'
import type { SFTPPartner } from '@/features/partners/types'

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/partners',
  component: PartnersPage,
})

export function PartnersPage() {
  const { partners, isLoading } = usePartners()

  const sftpPartners = partners.filter((p): p is SFTPPartner => p.type === 'SFTP');

  return (
    <div className="flex flex-col gap-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out p-8">

      {/* Header */}
      <section className="flex flex-col gap-2 pb-6 border-b border-slate-200/60">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 mb-2">
            <h2 className="text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-3">
              <Users className="w-8 h-8 text-indigo-600" />
              Trading Partners
            </h2>
          </div>
          <div className="flex-shrink-0">
            <CreateSftpPartnerModal />
          </div>
        </div>
      </section>

      {/* Main Grid */}
      <div className="space-y-8">
        <SftpPartnersTable data={sftpPartners} isLoading={isLoading} />
      </div>

    </div>
  )
}
