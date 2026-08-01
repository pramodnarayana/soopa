import { AS2PartnershipsPage } from '@soopa/edi-ui';
import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/platform/edi/as2partnerships')({
  component: AS2PartnershipsPage,
});
