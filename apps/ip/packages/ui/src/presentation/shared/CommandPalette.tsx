import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  StatusBadge,
} from '@soopa/ui';
import { Activity, Cable, Compass, GitMerge, Search, Sparkles, Workflow } from 'lucide-react';
import React, { useEffect, useMemo, useState } from 'react';
import { useSearchTracesByCorrelationQuery } from '../../application/use-trace-queries';
import type { IpNavigationPort } from '../../provider/IpRepositoriesContext';
import {
  buildCommandPaletteInstantCommands,
  buildCommandPaletteWorkspaceItems,
  CommandPaletteInstantActionKind,
  type CommandPaletteInstantActionKindValue,
  CommandPaletteWorkspaceId,
  type CommandPaletteWorkspaceIdValue,
  isCommandPaletteShortcutEvent,
} from './command-palette-actions';
import { mapTraceStatusTone } from './status-mapping';

export interface CommandPaletteProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly navigation: IpNavigationPort;
}

function renderInstantCommandIcon(kind: CommandPaletteInstantActionKindValue): React.ReactNode {
  switch (kind) {
    case CommandPaletteInstantActionKind.OPEN_TRACE_DETAIL:
      return <Activity className="h-4 w-4 text-brand-ink" />;
    case CommandPaletteInstantActionKind.OPEN_STITCH_RUN:
      return <Workflow className="h-4 w-4 text-brand-ink" />;
    case CommandPaletteInstantActionKind.SEARCH_CORRELATION:
    default:
      return <Search className="h-4 w-4 text-brand-ink" />;
  }
}

function renderInstantCommandText(
  kind: CommandPaletteInstantActionKindValue,
  targetId: string,
): React.ReactNode {
  switch (kind) {
    case CommandPaletteInstantActionKind.OPEN_TRACE_DETAIL:
      return (
        <span>
          Open 5-Layer Waterfall for <strong className="font-mono">{targetId}</strong>
        </span>
      );
    case CommandPaletteInstantActionKind.OPEN_STITCH_RUN:
      return (
        <span>
          Inspect Stitch Run <strong className="font-mono">{targetId}</strong>
        </span>
      );
    case CommandPaletteInstantActionKind.SEARCH_CORRELATION:
    default:
      return (
        <span>
          Search all traces for correlation <strong className="font-mono">{targetId}</strong>
        </span>
      );
  }
}

function renderWorkspaceIcon(id: CommandPaletteWorkspaceIdValue): React.ReactNode {
  switch (id) {
    case CommandPaletteWorkspaceId.COMMAND_CENTER:
      return <Compass className="h-4 w-4" />;
    case CommandPaletteWorkspaceId.TRACES:
      return <Activity className="h-4 w-4" />;
    case CommandPaletteWorkspaceId.CONNECTIONS:
      return <Cable className="h-4 w-4" />;
    case CommandPaletteWorkspaceId.TRANSFORMATIONS:
      return <GitMerge className="h-4 w-4" />;
    case CommandPaletteWorkspaceId.STITCHES:
    default:
      return <Workflow className="h-4 w-4" />;
  }
}

export function CommandPalette({ open, onOpenChange, navigation }: CommandPaletteProps) {
  const [query, setQuery] = useState('');
  const searchView = useSearchTracesByCorrelationQuery(query, 8);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (isCommandPaletteShortcutEvent(event)) {
        event.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onOpenChange]);

  const closeAndRun = (action: () => void): void => {
    onOpenChange(false);
    setQuery('');
    action();
  };

  const instantCommands = useMemo(
    () => buildCommandPaletteInstantCommands(query, navigation),
    [query, navigation],
  );
  const workspaceItems = useMemo(() => buildCommandPaletteWorkspaceItems(navigation), [navigation]);
  const matches = searchView.data ?? [];

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput
        placeholder="Search business correlation ID (e.g. MTR-700, ORD-99), trace ID (ip_trc_...), or jump to workspace..."
        value={query}
        onValueChange={setQuery}
      />
      <CommandList>
        <CommandEmpty>No matching correlation traces or workspaces.</CommandEmpty>

        {instantCommands.length > 0 ? (
          <CommandGroup heading="Instant Correlation & Entity Lookup">
            {instantCommands.map((cmd) => (
              <CommandItem
                key={cmd.value}
                value={cmd.value}
                onSelect={() => closeAndRun(cmd.execute)}
              >
                {renderInstantCommandIcon(cmd.kind)}
                {renderInstantCommandText(cmd.kind, cmd.targetId)}
              </CommandItem>
            ))}
          </CommandGroup>
        ) : null}

        {matches.length > 0 ? (
          <CommandGroup heading="Live Correlation Matches">
            {matches.map((item) => (
              <CommandItem
                key={item.traceId}
                value={`${item.traceId} ${item.correlationId ?? ''}`}
                onSelect={() => closeAndRun(() => navigation.toTraceDetail(item.traceId))}
              >
                <Sparkles className="h-4 w-4 text-brand-ink" />
                <div className="flex flex-1 items-center justify-between gap-2">
                  <span className="font-mono text-xs">{item.traceId}</span>
                  <StatusBadge label={item.status} tone={mapTraceStatusTone(item.status)} />
                </div>
              </CommandItem>
            ))}
          </CommandGroup>
        ) : null}

        <CommandSeparator />

        <CommandGroup heading="Workspaces">
          {workspaceItems.map((ws) => (
            <CommandItem key={ws.id} value={ws.value} onSelect={() => closeAndRun(ws.execute)}>
              {renderWorkspaceIcon(ws.id)}
              <span>{ws.label}</span>
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
