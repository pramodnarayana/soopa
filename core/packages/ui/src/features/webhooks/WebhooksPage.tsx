import { Network, Plus } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button } from '../../components/ui/button';
import type { WebhookHookConfig } from './api/webhookHooks';
import { useWebhooksQuery } from './api/webhookHooks';
import { CreateWebhookDialog } from './components/CreateWebhookDialog';
import { WebhooksTable } from './components/WebhooksTable';

export type WebhooksPageProps = WebhookHookConfig;

/**
 * Platform-level Webhooks management page.
 *
 * Accepts explicit (baseUrl, tenantId, token) as props — usable by any app
 * in the monorepo (UCP Dashboard, IDP, IP, etc.) without needing an EDI provider.
 */
export function WebhooksPage({ baseUrl, tenantId, token, httpClient, logger }: WebhooksPageProps) {
  const config = useMemo<WebhookHookConfig>(
    () => ({ baseUrl, tenantId, token, httpClient, logger }),
    [baseUrl, httpClient, logger, tenantId, token],
  );
  const { data: webhooks = [], isLoading } = useWebhooksQuery(config);
  const [showCreate, setShowCreate] = useState(false);

  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 flex flex-col gap-10 pb-12 duration-700 ease-out">
      <section className="flex flex-col gap-2 border-b border-slate-200/60 pb-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="flex items-center gap-3 text-3xl font-bold tracking-tight text-slate-900">
              <Network className="h-8 w-8 text-indigo-600" />
              Webhooks
            </h2>
          </div>
          <Button id="add-webhook-btn" type="button" size="cta" onClick={() => setShowCreate(true)}>
            <Plus className="mr-1 h-4 w-4" />
            Add Webhook
          </Button>
        </div>
        <p className="mt-1 text-sm text-slate-500">
          Configure HTTPS endpoints to receive real-time platform event notifications.
        </p>
      </section>

      <WebhooksTable config={config} data={webhooks} isLoading={isLoading} />

      <CreateWebhookDialog config={config} open={showCreate} onOpenChange={setShowCreate} />
    </div>
  );
}
