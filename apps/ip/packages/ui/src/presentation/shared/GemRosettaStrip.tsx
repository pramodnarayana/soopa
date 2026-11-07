import { CopyableIdPill } from '@soopa/ui';
import { ArrowRight, KeyRound } from 'lucide-react';
import React from 'react';
import type { GlobalEntityMapEntry } from '../../domain/trace';

export interface GemRosettaStripProps {
  readonly mappings: readonly GlobalEntityMapEntry[];
}

export function GemRosettaStrip({ mappings }: GemRosettaStripProps) {
  if (mappings.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-muted/30 p-4 text-xs text-muted-foreground">
        No GlobalEntityMap (GEM) cross-references recorded on this trace yet.
      </div>
    );
  }

  return (
    <div className="space-y-2.5">
      {mappings.map((gem) => (
        <div
          key={gem.id}
          className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-accent/40 px-4 py-3 text-xs"
        >
          <span className="inline-flex items-center gap-1.5 rounded-md bg-primary px-2 py-0.5 font-semibold text-primary-foreground">
            <KeyRound className="h-3.5 w-3.5" />
            <span>{gem.entityDomain}</span>
          </span>

          <CopyableIdPill
            value={gem.sourceEntityId}
            prefixLabel={`Src (${gem.sourceConnectionId.slice(0, 8)})`}
          />

          <ArrowRight aria-hidden="true" className="h-3.5 w-3.5 text-muted-foreground" />

          <CopyableIdPill value={gem.canonicalId} prefixLabel="GEM Canonical" />

          <ArrowRight aria-hidden="true" className="h-3.5 w-3.5 text-muted-foreground" />

          {gem.destEntityId ? (
            <CopyableIdPill
              value={gem.destEntityId}
              prefixLabel={`Dest (${(gem.destConnectionId ?? 'ext').slice(0, 8)})`}
            />
          ) : (
            <span className="rounded-md border border-dashed border-border px-2 py-0.5 text-muted-foreground">
              Pending Destination Binding
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
