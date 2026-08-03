import { TransactionsPage } from '@soopa/edi-ui';
import { createFileRoute, useNavigate } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/edi/transactions/')({
  component: TransactionsRoute,
});

function TransactionsRoute() {
  const navigate = useNavigate();
  return (
    <TransactionsPage
      onTraceClick={(traceId) =>
        void navigate({ to: '/tenant/edi/transactions/$traceId', params: { traceId } })
      }
    />
  );
}
