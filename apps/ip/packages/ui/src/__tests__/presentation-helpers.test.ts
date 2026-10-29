import { ApiErrorCode, StatusTone } from '@soopa/ui';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { ConnectorPropertySpec } from '../domain/catalog';
import {
  ConnectionHandshakeStatus,
  ConnectionStatus,
  ConnectorPropertyType,
  PipelineLayer,
  ReplayStage,
  StagePosture,
  StitchRunStatus,
  SyncRunStatus,
  TraceStatus,
  TransformationMode,
} from '../domain/enums';
import {
  buildFailedCheckProblem,
  isConnectionSnapshotVerified,
} from '../presentation/connections/connection-preflight';
import {
  isSecretConnectorProperty,
  SpecFormRenderer,
  splitSpecFormValues,
} from '../presentation/connections/SpecFormRenderer';
import {
  buildCommandPaletteInstantCommands,
  buildCommandPaletteWorkspaceItems,
  CommandPaletteInstantActionKind,
  CommandPaletteWorkspaceId,
  isCommandPaletteShortcutEvent,
} from '../presentation/shared/command-palette-actions';
import {
  formatBytesCompact,
  formatLayerLabel,
  formatRelativeTimestamp,
  formatReplayStageLabel,
  mapConnectionStatusTone,
  mapStagePostureTone,
  mapStitchRunStatusTone,
  mapSyncRunStatusTone,
  mapTraceStatusTone,
  mapTransformationModeTone,
  stringifyJsonPretty,
} from '../presentation/shared/status-mapping';
import { InMemoryNavigationFake } from '../testing';

const SPEC_URL: ConnectorPropertySpec = {
  name: 'base_url',
  label: 'Base URL',
  type: ConnectorPropertyType.SHORT_TEXT,
  required: true,
  defaultValue: null,
  description: null,
  options: [],
  oauthConfig: null,
};

const SPEC_SECRET: ConnectorPropertySpec = {
  name: 'api_secret',
  label: 'API Secret',
  type: ConnectorPropertyType.SECRET_TEXT,
  required: true,
  defaultValue: null,
  description: null,
  options: [],
  oauthConfig: null,
};

const SPEC_OAUTH: ConnectorPropertySpec = {
  name: 'oauth_token',
  label: 'OAuth Token',
  type: ConnectorPropertyType.OAUTH,
  required: false,
  defaultValue: null,
  description: null,
  options: [],
  oauthConfig: null,
};

const SAMPLE_SPECS: readonly ConnectorPropertySpec[] = [SPEC_URL, SPEC_SECRET, SPEC_OAUTH];

describe('IP Presentation Helpers: SpecFormRenderer & Semantic Status Mappers', () => {
  it('strictly isolates secretText and oauth fields into rawCredentials away from publicConfig', () => {
    expect(isSecretConnectorProperty(SPEC_URL)).toBe(false);
    expect(isSecretConnectorProperty(SPEC_SECRET)).toBe(true);
    expect(isSecretConnectorProperty(SPEC_OAUTH)).toBe(true);

    const split = splitSpecFormValues(SAMPLE_SPECS, {
      base_url: 'https://mdm.itron.local',
      api_secret: 'sec_live_99',
      oauth_token: '',
    });

    expect(split.publicConfig).toEqual({ base_url: 'https://mdm.itron.local' });
    expect(split.rawCredentials).toEqual({ api_secret: 'sec_live_99' });
  });

  it('maps operational statuses to WCAG-compliant non-brand status tones and formats units', () => {
    expect(mapTraceStatusTone(TraceStatus.DELIVERED)).toBe(StatusTone.HEALTHY);
    expect(mapTraceStatusTone(TraceStatus.FAILED)).toBe(StatusTone.CRITICAL);
    expect(mapTraceStatusTone('UNKNOWN_CUSTOM')).toBe(StatusTone.NEUTRAL);
    expect(mapConnectionStatusTone(ConnectionStatus.AUTH_EXPIRED)).toBe(StatusTone.WARNING);
    expect(mapConnectionStatusTone('UNKNOWN')).toBe(StatusTone.NEUTRAL);
    expect(mapSyncRunStatusTone(SyncRunStatus.SUCCEEDED)).toBe(StatusTone.HEALTHY);
    expect(mapSyncRunStatusTone('UNKNOWN')).toBe(StatusTone.NEUTRAL);
    expect(mapStitchRunStatusTone(StitchRunStatus.RUNNING)).toBe(StatusTone.REPLAY);
    expect(mapStitchRunStatusTone('UNKNOWN')).toBe(StatusTone.NEUTRAL);
    expect(mapTransformationModeTone(TransformationMode.SHADOW)).toBe(StatusTone.SHADOW);
    expect(mapTransformationModeTone('UNKNOWN')).toBe(StatusTone.NEUTRAL);
    expect(mapStagePostureTone(StagePosture.CRITICAL)).toBe(StatusTone.CRITICAL);
    expect(formatLayerLabel(PipelineLayer.L3_NORMALIZE)).toBe('L3 Canonical + GEM');
    expect(formatLayerLabel('CUSTOM_LAYER')).toBe('CUSTOM_LAYER');
    expect(formatReplayStageLabel(ReplayStage.RETRY_DELIVER)).toBe(
      'L5 · Retry Destination Delivery',
    );
    expect(formatRelativeTimestamp(null)).toBe('—');
    expect(formatRelativeTimestamp('not-a-date')).toBe('not-a-date');
    expect(formatRelativeTimestamp('2026-10-29T08:00:00Z')).toBeTruthy();
    expect(formatBytesCompact(512)).toBe('512 B');
    expect(formatBytesCompact(2048)).toBe('2.0 KB');
    expect(formatBytesCompact(2_097_152)).toBe('2.00 MB');
    expect(stringifyJsonPretty(null)).toBe('null');
    expect(stringifyJsonPretty({ ok: true })).toContain('"ok": true');
  });

  it('renders SpecFormRenderer across empty state and all 6 connector property types', () => {
    const emptyHtml = renderToStaticMarkup(
      React.createElement(SpecFormRenderer, {
        properties: [],
        values: {},
        onChangeValue: () => undefined,
      }),
    );
    expect(emptyHtml).toContain('no additional configuration properties');

    const allProps: readonly ConnectorPropertySpec[] = [
      ...SAMPLE_SPECS,
      {
        name: 'batch_size',
        label: 'Batch Size',
        type: ConnectorPropertyType.NUMBER,
        required: false,
        defaultValue: 500,
        description: 'Records per page',
        options: [],
        oauthConfig: null,
      },
      {
        name: 'verify_tls',
        label: 'Verify TLS',
        type: ConnectorPropertyType.BOOLEAN,
        required: false,
        defaultValue: true,
        description: null,
        options: [],
        oauthConfig: null,
      },
      {
        name: 'region',
        label: 'Grid Region',
        type: ConnectorPropertyType.DROPDOWN,
        required: true,
        defaultValue: 'us-west',
        description: 'Target AMI utility grid',
        options: [{ label: 'US West', value: 'us-west' }],
        oauthConfig: null,
      },
    ];

    const fullHtml = renderToStaticMarkup(
      React.createElement(SpecFormRenderer, {
        properties: allProps,
        values: { base_url: 'https://ami.local', verify_tls: true, batch_size: 250 },
        onChangeValue: () => undefined,
      }),
    );
    expect(fullHtml).toContain('Base URL');
    expect(fullHtml).toContain('API Secret');
    expect(fullHtml).toContain('OAuth Token');
    expect(fullHtml).toContain('Records per page');
    expect(fullHtml).toContain('Target AMI utility grid');
  });

  it('evaluates connection preflight verification snapshots and maps failed handshake problems', () => {
    const failedProblem = buildFailedCheckProblem({
      success: false,
      status: ConnectionHandshakeStatus.AUTH_FAILED,
      message: null,
      errorCode: null,
    });
    expect(failedProblem).toEqual({
      code: ApiErrorCode.VALIDATION_ERROR,
      status: 400,
      serverCode: 'CHECK_FAILED',
      message: 'Connector pre-flight check failed.',
    });

    const explicitProblem = buildFailedCheckProblem({
      success: false,
      status: ConnectionHandshakeStatus.AUTH_FAILED,
      message: 'Invalid OAuth2 client secret',
      errorCode: 'INVALID_CLIENT',
    });
    expect(explicitProblem.serverCode).toBe('INVALID_CLIENT');
    expect(explicitProblem.message).toBe('Invalid OAuth2 client secret');

    expect(
      isConnectionSnapshotVerified('{"a":1}', '{"a":1}', {
        success: true,
        status: ConnectionHandshakeStatus.VERIFIED,
        message: 'OK',
        errorCode: null,
      }),
    ).toBe(true);
    expect(
      isConnectionSnapshotVerified('{"a":2}', '{"a":1}', {
        success: true,
        status: ConnectionHandshakeStatus.VERIFIED,
        message: 'OK',
        errorCode: null,
      }),
    ).toBe(false);
    expect(isConnectionSnapshotVerified('{"a":1}', null, null)).toBe(false);
  });

  it('resolves Cmd+K/Ctrl+K shortcuts, correlation/trace/run instant jumps, and command palette workspace actions', () => {
    expect(isCommandPaletteShortcutEvent({ metaKey: true, ctrlKey: false, key: 'k' })).toBe(true);
    expect(isCommandPaletteShortcutEvent({ metaKey: false, ctrlKey: true, key: 'K' })).toBe(true);
    expect(isCommandPaletteShortcutEvent({ metaKey: false, ctrlKey: false, key: 'k' })).toBe(false);
    expect(isCommandPaletteShortcutEvent({ metaKey: true, ctrlKey: false, key: 'p' })).toBe(false);

    const nav = new InMemoryNavigationFake();
    expect(buildCommandPaletteInstantCommands('   ', nav)).toEqual([]);

    const corrCmds = buildCommandPaletteInstantCommands('  MTR-77410 ', nav);
    expect(corrCmds).toHaveLength(1);
    expect(corrCmds[0]?.kind).toBe(CommandPaletteInstantActionKind.SEARCH_CORRELATION);
    corrCmds[0]?.execute();

    const traceCmds = buildCommandPaletteInstantCommands('ip_trc_9988', nav);
    expect(traceCmds.map((c) => c.kind)).toEqual([
      CommandPaletteInstantActionKind.SEARCH_CORRELATION,
      CommandPaletteInstantActionKind.OPEN_TRACE_DETAIL,
    ]);
    traceCmds[1]?.execute();

    const runCmds = buildCommandPaletteInstantCommands('wfr_5544', nav);
    expect(runCmds.map((c) => c.kind)).toEqual([
      CommandPaletteInstantActionKind.SEARCH_CORRELATION,
      CommandPaletteInstantActionKind.OPEN_STITCH_RUN,
    ]);
    runCmds[1]?.execute();

    const workspaces = buildCommandPaletteWorkspaceItems(nav);
    expect(workspaces.map((w) => w.id)).toEqual([
      CommandPaletteWorkspaceId.COMMAND_CENTER,
      CommandPaletteWorkspaceId.TRACES,
      CommandPaletteWorkspaceId.CONNECTIONS,
      CommandPaletteWorkspaceId.TRANSFORMATIONS,
      CommandPaletteWorkspaceId.STITCHES,
    ]);
    for (const ws of workspaces) {
      ws.execute();
    }

    expect(nav.visited).toEqual([
      '/tenant/ip/traces?q=MTR-77410',
      '/tenant/ip/traces/ip_trc_9988',
      '/tenant/ip/stitches/runs/wfr_5544',
      '/tenant/ip',
      '/tenant/ip/traces',
      '/tenant/ip/connections',
      '/tenant/ip/transformations',
      '/tenant/ip/stitches',
    ]);
  });
});
