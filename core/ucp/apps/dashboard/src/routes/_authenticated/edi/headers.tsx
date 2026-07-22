import { createFileRoute } from '@tanstack/react-router';
import { EdiHeadersPage } from '@soopa/edi-ui';

export const Route = createFileRoute('/_authenticated/edi/headers')({
  component: EdiHeadersPage,
});
