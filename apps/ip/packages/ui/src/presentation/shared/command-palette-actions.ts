import type { IpNavigationPort } from '../../provider/IpRepositoriesContext';

export const CommandPaletteInstantActionKind = {
  SEARCH_CORRELATION: 'SEARCH_CORRELATION',
  OPEN_TRACE_DETAIL: 'OPEN_TRACE_DETAIL',
  OPEN_STITCH_RUN: 'OPEN_STITCH_RUN',
} as const;

export type CommandPaletteInstantActionKindValue =
  (typeof CommandPaletteInstantActionKind)[keyof typeof CommandPaletteInstantActionKind];

export interface CommandPaletteInstantCommand {
  readonly kind: CommandPaletteInstantActionKindValue;
  readonly value: string;
  readonly targetId: string;
  readonly execute: () => void;
}

export interface CommandPaletteShortcutLike {
  readonly metaKey: boolean;
  readonly ctrlKey: boolean;
  readonly key: string;
}

export function isCommandPaletteShortcutEvent(event: CommandPaletteShortcutLike): boolean {
  return (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k';
}

export function buildCommandPaletteInstantCommands(
  rawQuery: string,
  navigation: IpNavigationPort,
): readonly CommandPaletteInstantCommand[] {
  const trimmed = rawQuery.trim();
  if (!trimmed) {
    return [];
  }

  const commands: CommandPaletteInstantCommand[] = [
    {
      kind: CommandPaletteInstantActionKind.SEARCH_CORRELATION,
      value: `search-correlation-${trimmed}`,
      targetId: trimmed,
      execute: () => navigation.toTraces(trimmed),
    },
  ];

  if (trimmed.startsWith('ip_trc_') || trimmed.startsWith('trc_')) {
    commands.push({
      kind: CommandPaletteInstantActionKind.OPEN_TRACE_DETAIL,
      value: `open-trace-${trimmed}`,
      targetId: trimmed,
      execute: () => navigation.toTraceDetail(trimmed),
    });
  }

  if (trimmed.startsWith('wfr_') || trimmed.startsWith('run_')) {
    commands.push({
      kind: CommandPaletteInstantActionKind.OPEN_STITCH_RUN,
      value: `open-stitch-run-${trimmed}`,
      targetId: trimmed,
      execute: () => navigation.toStitchRun(trimmed),
    });
  }

  return commands;
}

export const CommandPaletteWorkspaceId = {
  COMMAND_CENTER: 'COMMAND_CENTER',
  TRACES: 'TRACES',
  CONNECTIONS: 'CONNECTIONS',
  TRANSFORMATIONS: 'TRANSFORMATIONS',
  STITCHES: 'STITCHES',
} as const;

export type CommandPaletteWorkspaceIdValue =
  (typeof CommandPaletteWorkspaceId)[keyof typeof CommandPaletteWorkspaceId];

export interface CommandPaletteWorkspaceCommand {
  readonly id: CommandPaletteWorkspaceIdValue;
  readonly value: string;
  readonly label: string;
  readonly execute: () => void;
}

export function buildCommandPaletteWorkspaceItems(
  navigation: IpNavigationPort,
): readonly CommandPaletteWorkspaceCommand[] {
  return [
    {
      id: CommandPaletteWorkspaceId.COMMAND_CENTER,
      value: 'workspace command center overview',
      label: 'IP Command Center',
      execute: () => navigation.toCommandCenter(),
    },
    {
      id: CommandPaletteWorkspaceId.TRACES,
      value: 'workspace support traces timeline replay',
      label: 'Support Timeline & 5-Layer Traces',
      execute: () => navigation.toTraces(),
    },
    {
      id: CommandPaletteWorkspaceId.CONNECTIONS,
      value: 'workspace connections catalog pull sync',
      label: 'Connections & Pull Sync Checkpoints',
      execute: () => navigation.toConnections(),
    },
    {
      id: CommandPaletteWorkspaceId.TRANSFORMATIONS,
      value: 'workspace transformations canonical shadow diff',
      label: 'L3 Transformations & Shadow Workbench',
      execute: () => navigation.toTransformations(),
    },
    {
      id: CommandPaletteWorkspaceId.STITCHES,
      value: 'workspace stitches dag orchestration runs',
      label: 'L4 Stitches & Durable DAG Runs',
      execute: () => navigation.toStitches(),
    },
  ];
}
