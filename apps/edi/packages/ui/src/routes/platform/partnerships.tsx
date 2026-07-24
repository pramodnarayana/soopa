import { createFileRoute } from '@tanstack/react-router';
import { Network } from 'lucide-react';
import { CreatePartnershipModal } from '@/features/partners/components/CreatePartnershipModal';
import { PartnershipsTable } from '@/features/partners/components/PartnershipsTable';
import {
  PlatformPartnersProvider,
  usePlatformPartners,
} from '@/features/partners/context/PlatformPartnersContext';

export const Route = createFileRoute('/platform/partnerships')({
  component: () => (
    <PlatformPartnersProvider>
      <PartnershipsPage />
    </PlatformPartnersProvider>
  ),
});

export function PartnershipsPage() {
  const { partners, partnerships, isLoading } = usePlatformPartners();

  return (
    <div className="p-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 bg-emerald-50 text-emerald-600 rounded-lg">
              <Network className="w-5 h-5" />
            </div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Partnerships</h1>
          </div>
        </div>
        <CreatePartnershipModal availablePartners={partners} />
      </div>
      <PartnershipsTable
        data={partnerships || []}
        availablePartners={partners || []}
        isLoading={isLoading}
      />
    </div>
  );
}
