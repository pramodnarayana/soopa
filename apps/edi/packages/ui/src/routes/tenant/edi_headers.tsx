import { createRoute } from '@tanstack/react-router'
import { Route as appRoute } from '../tenant'
import { EdiHeadersTable } from '@/features/edi_headers/components/EdiHeadersTable'
import { CreateEdiHeaderModal } from '@/features/edi_headers/components/CreateEdiHeaderModal'

export const Route = createRoute({
  getParentRoute: () => appRoute,
  path: '/edi_headers',
  component: EdiHeadersPage,
})

export function EdiHeadersPage() {
  return (
    <div className="flex flex-col gap-8 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">
      {/* Header */}
      <section className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-slate-200/60">
        <div>
          <h2 className="text-3xl md:text-4xl font-extrabold tracking-tight text-slate-900">
            EDI Headers
          </h2>
        </div>
        <div className="shrink-0">
          <CreateEdiHeaderModal />
        </div>
      </section>

      {/* Main Content */}
      <section>
        <EdiHeadersTable />
      </section>
    </div>
  )
}
