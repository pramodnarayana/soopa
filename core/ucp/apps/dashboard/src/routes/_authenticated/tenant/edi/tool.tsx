import { EdiToolPage } from '@soopa/edi-ui';
import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/edi/tool')({
  component: EdiToolPage,
});
