import { Network, Plus } from 'lucide-react';
import { useState } from 'react';
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
export function WebhooksPage({ baseUrl, tenantId, token }: WebhooksPageProps) {
  const config: WebhookHookConfig = { baseUrl, tenantId, token };
  const { data: webhooks = [], isLoading } = useWebhooksQuery(config);
  const [showCreate, setShowCreate] = useState(false);

  return (
    <div className="flex flex-col gap-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">
      {/* Page Header */}
      <section className="flex flex-col gap-2 pb-6 border-b border-slate-200/60">
        <div className="flex justify-between items-center">
          <div className="flex items-center gap-3">
            <h2 className="text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-3">
              <Network className="w-8 h-8 text-indigo-600" />
              Webhooks
            </h2>
          </div>
          <Button id="add-webhook-btn" onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4 mr-1" />
            Add Webhook
          </Button>
        </div>
        <p className="text-slate-500 text-sm mt-1">
          Configure HTTPS endpoints to receive real-time platform event notifications.
        </p>
      </section>

      <WebhooksTable config={config} data={webhooks} isLoading={isLoading} />

      <CreateWebhookDialog config={config} open={showCreate} onOpenChange={setShowCreate} />
    </div>
  );
}
