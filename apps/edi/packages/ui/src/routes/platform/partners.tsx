import { Server } from 'lucide-react';
import { As2PartnersTable } from '@/features/partners/components/As2PartnersTable';
import { CreatePartnerModal } from '@/features/partners/components/CreatePartnerModal';
import {
  AS2PartnersProvider,
  useAS2Partners,
} from '@/features/partners/context/AS2PartnersContext';
import type { AS2Partner } from '@/features/partners/types';

export function TradingPartnersPage() {
  return (
    <AS2PartnersProvider>
      <TradingPartnersPageContent />
    </AS2PartnersProvider>
  );
}

function TradingPartnersPageContent() {
  const { partners, partnersLoading, partnersError } = useAS2Partners();
  const isLoading = partnersLoading;
  const error = partnersError;

  const safePartners = Array.isArray(partners) ? partners : [];
  const localPartners = safePartners.filter((p): p is AS2Partner => p.type === 'AS2' && p.is_local);
  const remotePartners = safePartners.filter(
    (p): p is AS2Partner => p.type === 'AS2' && !p.is_local,
  );

  return (
    <div className="p-8">
      <div className="mb-8 flex items-center justify-between">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-2 bg-indigo-50 text-indigo-600 rounded-lg">
            <Server className="w-5 h-5" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Trading Partners</h1>
        </div>
        <CreatePartnerModal
          existingAs2Ids={
            safePartners
              .map((p) => (p.type === 'AS2' ? p.as2_id : null))
              .filter(Boolean) as string[]
          }
        />
      </div>

      {isLoading ? (
        <div className="space-y-4">
          <div className="h-10 bg-slate-100 rounded-md animate-pulse" />
          <div className="h-40 bg-slate-50 rounded-md animate-pulse" />
        </div>
      ) : error ? (
        <div className="p-6 text-center text-red-600 bg-red-50 rounded-lg border border-red-100">
          Failed to load partners: {error.message}
        </div>
      ) : localPartners.length === 0 && remotePartners.length === 0 ? (
        <As2PartnersTable data={[]} isLoading={false} />
      ) : (
        <div className="space-y-8">
          {localPartners.length > 0 && (
            <section>
              <h2 className="text-xl font-semibold text-slate-800 mb-4 px-2">Local Stations</h2>
              <As2PartnersTable data={localPartners} isLoading={isLoading} />
            </section>
          )}

          {remotePartners.length > 0 && (
            <section>
              <h2 className="text-xl font-semibold text-slate-800 mb-4 px-2">Remote Stations</h2>
              <As2PartnersTable data={remotePartners} isLoading={isLoading} />
            </section>
          )}
        </div>
      )}
    </div>
  );
}
