import { createFileRoute } from '@tanstack/react-router';
import { WebhooksPage } from '@soopa/edi-ui';

export const Route = createFileRoute('/_authenticated/edi/webhooks')({
  component: WebhooksPage,
});
