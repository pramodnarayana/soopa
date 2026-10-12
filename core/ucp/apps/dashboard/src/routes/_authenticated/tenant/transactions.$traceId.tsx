import { createFileRoute, redirect } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/transactions/$traceId')({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: '/tenant/edi/transactions/$traceId',
      params: { traceId: params.traceId },
    });
  },
  component: () => null,
});
