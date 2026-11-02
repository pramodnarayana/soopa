import { ApiErrorCode, StatusTone } from '@soopa/ui';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { ConnectorPropertySpec } from '../domain/catalog';
import {
  AuthType,
  ConnectionHandshakeStatus,
  ConnectionStatus,
  ConnectorPropertyKey,
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
  isPropertyVisible,
  isSecretConnectorProperty,
  resolvePropertyLabel,
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
  name: ConnectorPropertyKey.BASE_URL,
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
      [ConnectorPropertyKey.BASE_URL]: 'https://mdm.itron.local',
      api_secret: 'sec_live_99',
      oauth_token: '',
    });

    expect(split.publicConfig).toEqual({ [ConnectorPropertyKey.BASE_URL]: 'https://mdm.itron.local' });
    expect(split.rawCredentials).toEqual({ api_secret: 'sec_live_99' });

    const specWithDefaults: ConnectorPropertySpec[] = [
      {
        ...SPEC_URL,
        defaultValue: 'https://default.example.com',
      },
      {
        ...SPEC_SECRET,
        defaultValue: 'default_secret_key',
      },
    ];

    const splitDefaults = splitSpecFormValues(specWithDefaults, {});
    expect(splitDefaults.publicConfig).toEqual({ [ConnectorPropertyKey.BASE_URL]: 'https://default.example.com' });
    expect(splitDefaults.rawCredentials).toEqual({ api_secret: 'default_secret_key' });
  });

  it('dynamically filters credential fields and customizes labels based on selected auth_type', () => {
    const httpSpecs: readonly ConnectorPropertySpec[] = [
      SPEC_URL,
      {
        name: ConnectorPropertyKey.AUTH_TYPE,
        label: 'Authentication Type',
        type: ConnectorPropertyType.DROPDOWN,
        required: true,
        defaultValue: AuthType.BEARER_TOKEN,
        description: null,
        options: [
          { label: 'None', value: AuthType.NO_AUTH },
          { label: 'Bearer Token', value: AuthType.BEARER_TOKEN },
          { label: 'API Key', value: AuthType.API_KEY },
          { label: 'Basic Auth', value: AuthType.BASIC_AUTH },
          { label: 'OAuth2 Client Credentials', value: AuthType.OAUTH2_CLIENT_CREDENTIALS },
        ],
        oauthConfig: null,
      },
      {
        name: ConnectorPropertyKey.TOKEN,
        label: 'Bearer Token / API Key',
        type: ConnectorPropertyType.SECRET_TEXT,
        required: false,
        defaultValue: null,
        description: null,
        options: [],
        oauthConfig: null,
      },
      {
        name: ConnectorPropertyKey.PARAM_NAME,
        label: 'API Key Header / Query Name',
        type: ConnectorPropertyType.SHORT_TEXT,
        required: false,
        defaultValue: 'X-API-Key',
        description: null,
        options: [],
        oauthConfig: null,
      },
      {
        name: ConnectorPropertyKey.USERNAME,
        label: 'Basic Auth Username',
        type: ConnectorPropertyType.SHORT_TEXT,
        required: false,
        defaultValue: null,
        description: null,
        options: [],
        oauthConfig: null,
      },
      {
        name: ConnectorPropertyKey.PASSWORD,
        label: 'Basic Auth Password',
        type: ConnectorPropertyType.SECRET_TEXT,
        required: false,
        defaultValue: null,
        description: null,
        options: [],
        oauthConfig: null,
      },
      {
        name: ConnectorPropertyKey.TOKEN_URL,
        label: 'OAuth2 Token URL',
        type: ConnectorPropertyType.SHORT_TEXT,
        required: false,
        defaultValue: null,
        description: null,
        options: [],
        oauthConfig: null,
      },
    ];

    const tokenProp = httpSpecs.find((p) => p.name === ConnectorPropertyKey.TOKEN)!;
    const paramNameProp = httpSpecs.find((p) => p.name === ConnectorPropertyKey.PARAM_NAME)!;
    const usernameProp = httpSpecs.find((p) => p.name === ConnectorPropertyKey.USERNAME)!;
    const passwordProp = httpSpecs.find((p) => p.name === ConnectorPropertyKey.PASSWORD)!;
    const tokenUrlProp = httpSpecs.find((p) => p.name === ConnectorPropertyKey.TOKEN_URL)!;

    // Bearer Token auth
    expect(isPropertyVisible(tokenProp, { [ConnectorPropertyKey.AUTH_TYPE]: AuthType.BEARER_TOKEN }, httpSpecs)).toBe(true);
    expect(isPropertyVisible(paramNameProp, { [ConnectorPropertyKey.AUTH_TYPE]: AuthType.BEARER_TOKEN }, httpSpecs)).toBe(false);
    expect(isPropertyVisible(usernameProp, { [ConnectorPropertyKey.AUTH_TYPE]: AuthType.BEARER_TOKEN }, httpSpecs)).toBe(false);
    expect(isPropertyVisible(tokenUrlProp, { [ConnectorPropertyKey.AUTH_TYPE]: AuthType.BEARER_TOKEN }, httpSpecs)).toBe(false);
    expect(resolvePropertyLabel(tokenProp, AuthType.BEARER_TOKEN)).toBe('Bearer Token');

    // API Key auth
    expect(isPropertyVisible(tokenProp, { [ConnectorPropertyKey.AUTH_TYPE]: AuthType.API_KEY }, httpSpecs)).toBe(true);
    expect(isPropertyVisible(paramNameProp, { [ConnectorPropertyKey.AUTH_TYPE]: AuthType.API_KEY }, httpSpecs)).toBe(true);
    expect(isPropertyVisible(usernameProp, { [ConnectorPropertyKey.AUTH_TYPE]: AuthType.API_KEY }, httpSpecs)).toBe(false);
    expect(resolvePropertyLabel(tokenProp, AuthType.API_KEY)).toBe('API Key Secret');

    // Basic Auth
    expect(isPropertyVisible(tokenProp, { [ConnectorPropertyKey.AUTH_TYPE]: AuthType.BASIC_AUTH }, httpSpecs)).toBe(false);
    expect(isPropertyVisible(usernameProp, { [ConnectorPropertyKey.AUTH_TYPE]: AuthType.BASIC_AUTH }, httpSpecs)).toBe(true);
    expect(isPropertyVisible(passwordProp, { [ConnectorPropertyKey.AUTH_TYPE]: AuthType.BASIC_AUTH }, httpSpecs)).toBe(true);

    // OAuth2 Client Credentials
    expect(isPropertyVisible(tokenProp, { [ConnectorPropertyKey.AUTH_TYPE]: AuthType.OAUTH2_CLIENT_CREDENTIALS }, httpSpecs)).toBe(false);
    expect(isPropertyVisible(tokenUrlProp, { [ConnectorPropertyKey.AUTH_TYPE]: AuthType.OAUTH2_CLIENT_CREDENTIALS }, httpSpecs)).toBe(true);

    // No Auth
    expect(isPropertyVisible(tokenProp, { [ConnectorPropertyKey.AUTH_TYPE]: AuthType.NO_AUTH }, httpSpecs)).toBe(false);
    expect(isPropertyVisible(usernameProp, { [ConnectorPropertyKey.AUTH_TYPE]: AuthType.NO_AUTH }, httpSpecs)).toBe(false);

    // Splitting values omits hidden fields with defaults (e.g. param_name with default X-API-Key is omitted in BEARER_TOKEN)
    const bearerSplit = splitSpecFormValues(httpSpecs, {
      [ConnectorPropertyKey.BASE_URL]: 'https://api.github.com',
      [ConnectorPropertyKey.AUTH_TYPE]: AuthType.BEARER_TOKEN,
      [ConnectorPropertyKey.TOKEN]: 'ghp_secret123',
      [ConnectorPropertyKey.USERNAME]: 'should_be_ignored',
    });
    expect(bearerSplit.publicConfig).toEqual({
      [ConnectorPropertyKey.BASE_URL]: 'https://api.github.com',
      [ConnectorPropertyKey.AUTH_TYPE]: AuthType.BEARER_TOKEN,
    });
    expect(bearerSplit.rawCredentials).toEqual({
      [ConnectorPropertyKey.TOKEN]: 'ghp_secret123',
    });
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
