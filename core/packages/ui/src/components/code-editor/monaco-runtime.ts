import Editor, { DiffEditor, loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import EditorWorker from 'monaco-editor/editor/editor.worker?worker';
import CssWorker from 'monaco-editor/language/css/css.worker?worker';
import HtmlWorker from 'monaco-editor/language/html/html.worker?worker';
import JsonWorker from 'monaco-editor/language/json/json.worker?worker';
import TsWorker from 'monaco-editor/language/typescript/ts.worker?worker';
import { configureMonacoEnvironment } from './monaco-config';

let runtimeConfigured = false;

export function ensureSelfHostedMonacoConfigured(): void {
  if (runtimeConfigured) {
    return;
  }
  runtimeConfigured = true;
  configureMonacoEnvironment(monaco, loader, {
    workers: {
      editor: EditorWorker,
      json: JsonWorker,
      css: CssWorker,
      html: HtmlWorker,
      ts: TsWorker,
    },
    environmentTarget: globalThis,
  });
}

ensureSelfHostedMonacoConfigured();

export { DiffEditor as SelfHostedMonacoDiffEditor, Editor as SelfHostedMonacoEditor };
