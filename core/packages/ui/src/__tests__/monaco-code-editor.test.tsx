import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import {
  CodeViewer,
  configureMonacoEnvironment,
  isDragLeavingContainer,
  MonacoCodeEditor,
  MonacoCodeViewer,
  MonacoFileToolbarVisibility,
  MonacoJsonDiffViewer,
  processUploadedEditorFile,
} from '../components/code-editor';

describe('Unified @soopa/ui code-editor module', () => {
  it('configures self-hosted Monaco loader and strict RFC 8259 JSON diagnostics without CDN or schema fetches', () => {
    let capturedDiagnostics: unknown = null;
    let capturedLoaderConfig: unknown = null;

    const fakeMonaco = {
      json: {
        jsonDefaults: {
          setDiagnosticsOptions: (opts: unknown) => {
            capturedDiagnostics = opts;
          },
        },
      },
    };
    const fakeLoader = {
      config: (cfg: unknown) => {
        capturedLoaderConfig = cfg;
      },
    };

    configureMonacoEnvironment(fakeMonaco, fakeLoader);

    expect(capturedDiagnostics).toEqual({
      validate: true,
      allowComments: false,
      trailingCommas: 'error',
      comments: 'error',
      enableSchemaRequest: false,
    });
    expect(capturedLoaderConfig).toEqual({ monaco: fakeMonaco });
  });

  it('wires Vite-bundled MonacoEnvironment.getWorker for editor, JSON, CSS, HTML, and TypeScript labels', () => {
    class FakeEditorWorker {
      readonly kind = 'editor';
    }
    class FakeJsonWorker {
      readonly kind = 'json';
    }
    class FakeCssWorker {
      readonly kind = 'css';
    }
    class FakeHtmlWorker {
      readonly kind = 'html';
    }
    class FakeTsWorker {
      readonly kind = 'ts';
    }

    const fakeMonaco = {
      json: {
        jsonDefaults: {
          setDiagnosticsOptions: () => undefined,
        },
      },
    };
    const fakeLoader = {
      config: () => undefined,
    };
    const envTarget: {
      MonacoEnvironment?: {
        getWorker(workerId: string, label: string): { readonly kind: string };
      };
    } = {};

    configureMonacoEnvironment(fakeMonaco, fakeLoader, {
      workers: {
        editor: FakeEditorWorker,
        json: FakeJsonWorker,
        css: FakeCssWorker,
        html: FakeHtmlWorker,
        ts: FakeTsWorker,
      },
      environmentTarget: envTarget,
    });

    expect(envTarget.MonacoEnvironment).toBeDefined();
    expect(envTarget.MonacoEnvironment?.getWorker('w1', 'json').kind).toBe('json');
    expect(envTarget.MonacoEnvironment?.getWorker('w2', 'scss').kind).toBe('css');
    expect(envTarget.MonacoEnvironment?.getWorker('w3', 'html').kind).toBe('html');
    expect(envTarget.MonacoEnvironment?.getWorker('w4', 'typescript').kind).toBe('ts');
    expect(envTarget.MonacoEnvironment?.getWorker('w5', 'edi').kind).toBe('editor');
  });

  it('prevents child-node dragleave flicker via containment check', () => {
    const childToken = { id: 'child' };
    const outsideToken = { id: 'outside' };
    const fakeContainer = {
      containsNode: (candidate: unknown): boolean => candidate === childToken,
    };

    expect(isDragLeavingContainer(fakeContainer, childToken)).toBe(false);
    expect(isDragLeavingContainer(fakeContainer, outsideToken)).toBe(true);
    expect(isDragLeavingContainer(fakeContainer, null)).toBe(true);
  });

  it('renders MonacoCodeEditor, strictly read-only MonacoCodeViewer, and MonacoJsonDiffViewer from unified taxonomy', () => {
    expect(CodeViewer).toBe(MonacoCodeViewer);

    const editorHtml = renderToStaticMarkup(
      <MonacoCodeEditor
        value='{"order_id":"ORD-1"}'
        onChange={() => undefined}
        language="json"
        height={260}
        ariaLabelledBy="blueprint-label"
      />,
    );
    expect(editorHtml).toContain('height:260px');
    expect(editorHtml).toContain('aria-labelledby="blueprint-label"');
    expect(editorHtml).not.toContain('Upload File');

    const viewerHtml = renderToStaticMarkup(
      <MonacoCodeViewer value='{"status":"ACTIVE"}' language="json" height={200} />,
    );
    expect(viewerHtml).toContain('height:200px');
    expect(viewerHtml).toContain('Copy');

    const diffHtml = renderToStaticMarkup(
      <MonacoJsonDiffViewer
        originalValue='{"v":1}'
        modifiedValue='{"v":2}'
        onModifiedChange={() => undefined}
      />,
    );
    expect(diffHtml).toContain('height:380px');
  });

  it('renders accessible visually-hidden file input and toolbar when toolbarVisibility is ALWAYS', () => {
    const html = renderToStaticMarkup(
      <MonacoCodeEditor
        value='{"order_id":"ORD-1"}'
        onChange={() => undefined}
        language="json"
        height={280}
        fileUpload={{
          accept: '.json,application/json',
          buttonLabel: 'Upload .json',
          statusText: 'orders.json',
          toolbarVisibility: MonacoFileToolbarVisibility.ALWAYS,
        }}
      />,
    );

    expect(html).toContain('Upload .json');
    expect(html).toContain('orders.json');
    expect(html).toContain('type="file"');
    expect(html).toContain('sr-only');
    expect(html).not.toContain('class="hidden"');
  });

  it('hides toolbar when editor has content and toolbarVisibility is EMPTY_ONLY, and shows it when empty', () => {
    const filledHtml = renderToStaticMarkup(
      <MonacoCodeEditor
        value="ISA*00*..."
        onChange={() => undefined}
        language="edi"
        fileUpload={{
          accept: '.edi,.json',
          emptyPrompt: 'Drag & drop or paste EDI',
          toolbarVisibility: MonacoFileToolbarVisibility.EMPTY_ONLY,
        }}
      />,
    );
    expect(filledHtml).not.toContain('Upload File');
    expect(filledHtml).not.toContain('Drag &amp; drop or paste EDI');

    const emptyHtml = renderToStaticMarkup(
      <MonacoCodeEditor
        value=""
        onChange={() => undefined}
        language="edi"
        cornerPlaceholder="-----BEGIN CERTIFICATE-----"
        statusBanner={<div>Certificate Ready</div>}
        fileUpload={{
          accept: '.pem',
          emptyPrompt: null,
          toolbarVisibility: MonacoFileToolbarVisibility.EMPTY_ONLY,
        }}
      />,
    );
    expect(emptyHtml).toContain('Upload File');
    expect(emptyHtml).toContain('-----BEGIN CERTIFICATE-----');
    expect(emptyHtml).toContain('Certificate Ready');
  });

  it('processes valid files, enforces maxBytes, and runs transformLoadedFile without throwing', async () => {
    const validFile = new File(['{"id":1}'], 'orders.json', { type: 'application/json' });
    const accepted = await processUploadedEditorFile(validFile, {
      maxBytes: 1024,
      transformLoadedFile: (raw) => {
        const parsed: unknown = JSON.parse(raw);
        return { ok: true, content: JSON.stringify(parsed, null, 2) };
      },
    });
    expect(accepted).toEqual({
      ok: true,
      content: '{\n  "id": 1\n}',
    });

    const oversizedFile = new File(['x'.repeat(64)], 'large.json', { type: 'application/json' });
    const rejectedSize = await processUploadedEditorFile(oversizedFile, {
      maxBytes: 16,
    });
    expect(rejectedSize.ok).toBe(false);
    if (!rejectedSize.ok) {
      expect(rejectedSize.reason).toContain('exceeds');
    }

    const malformedFile = new File(['{bad json'], 'broken.json', { type: 'application/json' });
    const rejectedTransform = await processUploadedEditorFile(malformedFile, {
      transformLoadedFile: (raw, file) => {
        try {
          JSON.parse(raw);
          return { ok: true, content: raw };
        } catch {
          return { ok: false, reason: `Invalid JSON in ${file.name}` };
        }
      },
    });
    expect(rejectedTransform).toEqual({
      ok: false,
      reason: 'Invalid JSON in broken.json',
    });
  });
});
