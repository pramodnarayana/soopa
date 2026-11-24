import { createFileRoute, redirect } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/ip/')({
  beforeLoad: () => {
    throw redirect({ to: '/tenant/ip/stitches' });
  },
  component: () => null,
});
