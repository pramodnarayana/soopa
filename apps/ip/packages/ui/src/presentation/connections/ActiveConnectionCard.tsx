import { Button, StatusBadge, StatusTone } from '@soopa/ui';
import { Check, Copy, Trash2 } from 'lucide-react';
import React, { useState } from 'react';
import { toast } from 'sonner';
import type { CatalogAppSummary } from '../../domain/catalog';
import { buildIngressWebhookUrl, type Connection } from '../../domain/connection';
import { mapConnectionStatusTone } from '../shared/status-mapping';

export interface ActiveConnectionCardProps {
  readonly connection: Connection;
  readonly catalogApp?: CatalogAppSummary;
  readonly appIcon: React.ReactNode;
  readonly baseUrl?: string;
  readonly tenantId: string;
  readonly onOpenDetail: (connectionId: string) => void;
  readonly onRequestDelete: (connection: Connection) => void;
}

export function ActiveConnectionCard({
  connection,
  catalogApp,
  appIcon,
  baseUrl,
  tenantId,
  onOpenDetail,
  onRequestDelete,
}: ActiveConnectionCardProps) {
  const [copied, setCopied] = useState(false);
  const webhookUrl = buildIngressWebhookUrl(baseUrl, tenantId, connection.id);

  const handleCopyWebhook = async (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(webhookUrl);
      setCopied(true);
      toast.success(`Copied webhook URL for "${connection.name}"`);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error('Unable to copy webhook URL to clipboard.');
    }
  };

  return (
    <div
      tabIndex={0}
      role="button"
      onClick={() => onOpenDetail(connection.id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpenDetail(connection.id);
        }
      }}
      className="flex cursor-pointer flex-col justify-between rounded-2xl border border-border bg-card p-5 text-left shadow-xs transition-all hover:border-primary/50 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border bg-muted/60">
            {appIcon}
          </div>
          <div className="min-w-0">
            <h3 className="truncate font-semibold text-foreground text-sm leading-tight">
              {connection.name}
            </h3>
            <span className="block truncate font-mono text-xs text-muted-foreground">
              {catalogApp?.displayName ?? connection.appId} · {connection.appId}
            </span>
          </div>
        </div>
        <StatusBadge label={connection.status} tone={mapConnectionStatusTone(connection.status)} />
      </div>

      <div className="mt-5 flex items-center justify-between border-t border-border/60 pt-3">
        <StatusBadge label={connection.authType} tone={StatusTone.NEUTRAL} />

        <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={(e) => void handleCopyWebhook(e)}
            className="h-8 gap-1.5 text-xs font-medium"
            title={webhookUrl}
          >
            {copied ? (
              <>
                <Check className="h-3.5 w-3.5 text-status-healthy-fg" />
                <span>Copied</span>
              </>
            ) : (
              <>
                <Copy className="h-3.5 w-3.5" />
                <span>Copy Webhook</span>
              </>
            )}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
            onClick={(e) => {
              e.stopPropagation();
              onRequestDelete(connection);
            }}
            title={`Delete ${connection.name}`}
            aria-label={`Delete ${connection.name}`}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
