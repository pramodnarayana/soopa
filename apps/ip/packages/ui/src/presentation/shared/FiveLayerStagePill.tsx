import { Button, cn, StatusBadge } from '@soopa/ui';
import { ChevronRight } from 'lucide-react';
import React from 'react';
import type { PipelineLayerValue } from '../../domain/enums';
import type { PipelineLayerSummary } from '../../domain/replay/derive-replay-eligibility';
import { formatLayerLabel, mapStagePostureTone } from './status-mapping';

export interface FiveLayerStageStripProps {
  readonly layers: readonly PipelineLayerSummary[];
  readonly activeLayer: PipelineLayerValue;
  readonly onSelectLayer: (layer: PipelineLayerValue) => void;
}

export function FiveLayerStageStrip({
  layers,
  activeLayer,
  onSelectLayer,
}: FiveLayerStageStripProps) {
  return (
    <div
      role="tablist"
      aria-label="5-Layer Integration Pipeline Waterfall"
      className="grid grid-cols-1 gap-2.5 md:grid-cols-5"
    >
      {layers.map((item, idx) => {
        const isSelected = item.layer === activeLayer;
        const tone = mapStagePostureTone(item.posture);
        return (
          <div key={item.layer} className="relative flex items-stretch">
            <Button
              type="button"
              role="tab"
              aria-selected={isSelected}
              variant={isSelected ? 'secondary' : 'outline'}
              onClick={() => onSelectLayer(item.layer)}
              className={cn(
                'h-auto w-full flex-col items-start gap-2 rounded-xl p-3.5 text-left transition-all',
                isSelected &&
                  'border-primary ring-2 ring-primary/40 bg-accent text-accent-foreground',
              )}
            >
              <div className="flex w-full items-center justify-between gap-2">
                <span className="text-xs font-bold tracking-tight text-foreground">
                  {item.label}
                </span>
                <StatusBadge label={item.posture} tone={tone} />
              </div>
              <div className="w-full truncate text-xs text-muted-foreground">{item.subtitle}</div>
              <div className="font-mono text-xs font-medium text-brand-ink tabular-nums">
                {item.countLabel}
              </div>
            </Button>
            {idx < layers.length - 1 ? (
              <ChevronRight
                aria-hidden="true"
                className="pointer-events-none hidden h-4 w-4 shrink-0 self-center text-muted-foreground md:ml-1 md:block"
              />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function LayerTagBadge({ layer }: { readonly layer: string }) {
  return (
    <span className="inline-flex items-center rounded-md border border-border bg-accent/60 px-2 py-0.5 font-mono text-xs font-medium text-accent-foreground">
      {formatLayerLabel(layer)}
    </span>
  );
}
