import { createRoute, useParams, useRouter } from '@tanstack/react-router';
import { ArrowLeft } from 'lucide-react';
import { useTransactionDetail } from '../../../features/transactions/api/transactionsApi';
import { TransactionTimeline } from '../../../features/transactions/components/TransactionTimeline';
import { Route as transactionsRoute } from './index';

export const Route = createRoute({
  getParentRoute: () => transactionsRoute,
  path: '$traceId',
  component: TracePageWrapper,
});

function TracePageWrapper() {
  const { traceId } = useParams({ from: Route.id });
  const router = useRouter();
  return <TransactionTracePage traceId={traceId} onBack={() => router.history.back()} />;
}

interface TransactionTracePageProps {
  traceId: string;
  onBack?: () => void;
}

/**
 * Renders the full 3-stage trace timeline for a single EDI transaction.
 *
 * This is the Transactions-scoped version of the trace view.
 * The back button navigates to /tenant/edi/transactions, NOT /tenant/edi/explorer.
 */
export function TransactionTracePage({ traceId, onBack }: TransactionTracePageProps) {
  const { data, isLoading, isError } = useTransactionDetail(traceId);

  return (
    <div className="max-w-7xl mx-auto">
      {/* Back navigation */}
      {onBack && (
        <div className="mb-6">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center gap-2 text-sm font-medium text-slate-500 hover:text-indigo-600 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Transactions
          </button>
        </div>
      )}

      {/* Loading state */}
      {isLoading && (
        <div className="flex flex-col items-center justify-center py-24 gap-4">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-500 border-t-transparent" />
          <p className="text-slate-500 font-medium">Loading transaction trace...</p>
        </div>
      )}

      {/* Error state */}
      {(isError || (!isLoading && !data)) && (
        <div className="text-center py-24 bg-white rounded-xl border border-red-100 shadow-sm">
          <p className="text-red-500 font-semibold mb-2">Transaction trace not found</p>
          <p className="text-slate-500 text-sm">
            Trace ID <span className="font-mono bg-red-50 px-1.5 py-0.5 rounded">{traceId}</span>{' '}
            could not be found or you don't have access.
          </p>
        </div>
      )}

      {/* Timeline */}
      {data && !isLoading && <TransactionTimeline transaction={data} />}
    </div>
  );
}
