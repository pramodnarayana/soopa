import Editor, { DiffEditor, loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import { configureMonacoEnvironment } from './monaco-config';

let runtimeConfigured = false;

function ensureSelfHostedMonacoConfigured(): void {
  if (runtimeConfigured) {
    return;
  }
  runtimeConfigured = true;
  configureMonacoEnvironment(monaco, loader);
}

ensureSelfHostedMonacoConfigured();

export { DiffEditor as SelfHostedMonacoDiffEditor, Editor as SelfHostedMonacoEditor };
