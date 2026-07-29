import { ArrowLeft } from 'lucide-react';
import { useTransactionDetail } from '../../../features/transactions/api/transactionsApi';
import { TransactionTimeline } from '../../../features/transactions/components/TransactionTimeline';

export function TransactionDetailPage({
  traceId,
  onBack,
}: {
  traceId: string;
  onBack?: () => void;
}) {
  const { data, isLoading, isError } = useTransactionDetail(traceId);

  return (
    <div className="p-8 max-w-7xl mx-auto">
      {onBack && (
        <div className="mb-6">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center gap-2 text-sm font-medium text-slate-500 hover:text-indigo-600 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Data Explorer
          </button>
        </div>
      )}

      {isLoading ? (
        <div className="flex flex-col items-center justify-center py-24 gap-4">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-500 border-t-transparent" />
          <p className="text-slate-500 font-medium">Loading transaction details...</p>
        </div>
      ) : isError || !data ? (
        <div className="text-center py-24 bg-white rounded-xl border border-red-100 shadow-sm">
          <p className="text-red-500 font-semibold mb-2">Error loading transaction</p>
          <p className="text-slate-500 text-sm">
            The trace ID {traceId} could not be found or you don't have access.
          </p>
        </div>
      ) : (
        <TransactionTimeline transaction={data} />
      )}
    </div>
  );
}
