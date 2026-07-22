import { createFileRoute } from '@tanstack/react-router'
import { ExplorerLayout } from '@/features/explorer/components/ExplorerLayout'

export const Route = createFileRoute('/tenant/explorer/')({
  component: ExplorerPage,
})

function ExplorerPage() {
  return (
    <div className="p-8 max-w-7xl mx-auto">
      <ExplorerLayout />
    </div>
  )
}
