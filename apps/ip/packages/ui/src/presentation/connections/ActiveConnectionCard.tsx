import { Button, StatusBadge, StatusTone } from '@soopa/ui';
import { ArrowUpRight, Check, Copy, Trash2 } from 'lucide-react';
import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import type { CatalogAppSummary } from '../../domain/catalog';
import { buildIngressWebhookUrl, type Connection } from '../../domain/connection';
import { mapConnectionStatusTone } from '../shared/status-mapping';

const COPY_FEEDBACK_RESET_MS = 2000;

export interface ActiveConnectionCardProps {
  readonly connection: Connection;
  readonly catalogApp?: CatalogAppSummary;
  readonly appIcon: React.ReactNode;
  readonly baseUrl?: string;
  readonly tenantSlug: string;
  readonly onOpenDetail: (connectionId: string) => void;
  readonly onRequestDelete: (connection: Connection) => void;
}

export interface CardKeyDownInspectionEvent {
  readonly key: string;
  readonly target: unknown;
  readonly currentTarget: unknown;
}

export function shouldActivateCardOnKeyDown(event: CardKeyDownInspectionEvent): boolean {
  if (event.target !== event.currentTarget) {
    return false;
  }
  return event.key === 'Enter' || event.key === ' ';
}

export function ActiveConnectionCard({
  connection,
  catalogApp,
  appIcon,
  baseUrl,
  tenantSlug,
  onOpenDetail,
  onRequestDelete,
}: ActiveConnectionCardProps): React.JSX.Element {
  const [copiedWebhook, setCopiedWebhook] = useState(false);
  const copyResetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (copyResetTimerRef.current !== null) {
        clearTimeout(copyResetTimerRef.current);
      }
    };
  }, []);

  const handleCopyWebhook = async (): Promise<void> => {
    try {
      const webhookUrl = buildIngressWebhookUrl(
        baseUrl,
        tenantSlug,
        connection.appId,
        connection.id,
      );
      await navigator.clipboard.writeText(webhookUrl);
      setCopiedWebhook(true);
      toast.success('Webhook URL copied to clipboard.');
      if (copyResetTimerRef.current !== null) {
        clearTimeout(copyResetTimerRef.current);
      }
      copyResetTimerRef.current = setTimeout(() => {
        copyResetTimerRef.current = null;
        setCopiedWebhook(false);
      }, COPY_FEEDBACK_RESET_MS);
    } catch {
      toast.error('Unable to copy webhook URL to clipboard.');
    }
  };

  return (
    <article
      onKeyDown={(e) => {
        if (shouldActivateCardOnKeyDown(e)) {
          e.preventDefault();
          onOpenDetail(connection.id);
        }
      }}
      className="relative flex flex-col justify-between rounded-2xl border border-border bg-card p-5 text-left shadow-xs transition-all hover:border-primary/50 hover:shadow-md has-[button.card-primary-action:focus-visible]:ring-2 has-[button.card-primary-action:focus-visible]:ring-ring"
    >
      <header className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border bg-muted/60">
            {appIcon}
          </div>
          <div className="min-w-0">
            <h3 className="truncate font-semibold text-foreground text-sm leading-tight">
              <button
                type="button"
                onClick={() => onOpenDetail(connection.id)}
                className="card-primary-action cursor-pointer truncate text-left font-semibold text-foreground text-sm leading-tight after:absolute after:inset-0 focus-visible:outline-none"
              >
                {connection.name}
              </button>
            </h3>
            <span className="block truncate font-mono text-xs text-muted-foreground">
              {catalogApp?.displayName ?? connection.appId} · {connection.appId}
            </span>
          </div>
        </div>
        <StatusBadge label={connection.status} tone={mapConnectionStatusTone(connection.status)} />
      </header>

      <footer className="mt-5 flex items-center justify-between border-t border-border/60 pt-3">
        <StatusBadge label={connection.authType} tone={StatusTone.NEUTRAL} />

        <div className="relative z-10 flex items-center gap-1.5">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!tenantSlug.trim()}
            onClick={() => void handleCopyWebhook()}
            className="h-8 gap-1.5 text-xs font-medium"
          >
            {copiedWebhook ? (
              <>
                <Check className="h-3.5 w-3.5 text-emerald-600" />
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
            variant="outline"
            size="sm"
            onClick={() => onOpenDetail(connection.id)}
            className="h-8 gap-1.5 text-xs font-medium"
          >
            <ArrowUpRight className="h-3.5 w-3.5" />
            <span>Manage Entities</span>
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
            onClick={() => onRequestDelete(connection)}
            aria-label={`Delete ${connection.name}`}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </footer>
    </article>
  );
}
