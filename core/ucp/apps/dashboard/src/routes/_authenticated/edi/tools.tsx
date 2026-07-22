import { createFileRoute } from '@tanstack/react-router';
import { EdiToolPage } from '@soopa/edi-ui';

export const Route = createFileRoute('/_authenticated/edi/tools')({
  component: EdiToolPage,
});
