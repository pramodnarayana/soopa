import { WebhooksPage } from '@soopa/edi-ui';
import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/edi/webhooks')({
  component: WebhooksPage,
});
