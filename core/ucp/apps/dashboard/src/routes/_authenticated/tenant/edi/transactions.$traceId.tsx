import { TransactionTracePage } from '@soopa/edi-ui';
import { createFileRoute, useNavigate } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/edi/transactions/$traceId')({
  component: TransactionTraceRoute,
});

/**
 * Dashboard route wrapper for the Transaction Trace view.
 *
 * Responsibilities:
 *  - Extract `traceId` from TanStack Router route params
 *  - Provide the `onBack` callback using `useNavigate`
 *  - Delegate all rendering to the `TransactionTracePage` component in @soopa/edi-ui
 */
function TransactionTraceRoute() {
  const { traceId } = Route.useParams();
  const navigate = useNavigate();

  return (
    <TransactionTracePage
      traceId={traceId}
      onBack={() => void navigate({ to: '/tenant/edi/transactions' })}
    />
  );
}
