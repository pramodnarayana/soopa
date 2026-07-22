import { createFileRoute } from '@tanstack/react-router';
import { PartnersPage } from '@soopa/edi-ui';

export const Route = createFileRoute('/_authenticated/edi/partners')({
  component: PartnersPage,
});
