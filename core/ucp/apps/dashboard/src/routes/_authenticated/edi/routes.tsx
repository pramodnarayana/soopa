import { createFileRoute } from '@tanstack/react-router';
import { RoutesPage } from '@soopa/edi-ui';

export const Route = createFileRoute('/_authenticated/edi/routes')({
  component: RoutesPage,
});
