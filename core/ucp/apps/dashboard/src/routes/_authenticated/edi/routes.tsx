import { RoutesPage } from '@soopa/edi-ui';
import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/edi/routes')({
  component: RoutesPage,
});
