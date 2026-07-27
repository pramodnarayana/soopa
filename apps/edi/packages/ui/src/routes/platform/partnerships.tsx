import { Network } from 'lucide-react';
import { CreatePartnershipModal } from '@/features/partners/components/CreatePartnershipModal';
import { PartnershipsTable } from '@/features/partners/components/PartnershipsTable';
import {
  AS2PartnersProvider,
  useAS2Partners,
} from '@/features/partners/context/AS2PartnersContext';

export function PartnershipsPage() {
  return (
    <AS2PartnersProvider>
      <PartnershipsPageContent />
    </AS2PartnersProvider>
  );
}

function PartnershipsPageContent() {
  const { partners, partnerships, isLoading, error } = useAS2Partners();

  const safePartners = Array.isArray(partners) ? partners : [];
  const safePartnerships = Array.isArray(partnerships) ? partnerships : [];

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
        <CreatePartnershipModal availablePartners={safePartners} />
      </div>
      {error ? (
        <div className="p-6 text-center text-red-600 bg-red-50 rounded-lg border border-red-100">
          Failed to load partnerships: {error.message}
        </div>
      ) : (
        <PartnershipsTable
          data={safePartnerships}
          availablePartners={safePartners}
          isLoading={isLoading}
        />
      )}
    </div>
  );
}
