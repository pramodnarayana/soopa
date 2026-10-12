import { createFileRoute, redirect } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/transactions/')({
  beforeLoad: () => {
    throw redirect({
      to: '/tenant/edi/transactions',
    });
  },
  component: () => null,
});
