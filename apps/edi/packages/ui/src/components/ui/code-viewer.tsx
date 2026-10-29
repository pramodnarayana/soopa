import { MonacoCodeViewer } from '@soopa/ui';
import React from 'react';
import { registerEdiLanguageAndTheme } from '../../utils/monaco-edi';

export interface CodeViewerProps {
  readonly value: string;
  readonly language?: 'edi' | 'json' | 'plaintext';
  readonly className?: string;
  readonly height?: string | number;
}

export function CodeViewer({
  value,
  language = 'json',
  className = '',
  height = '100%',
}: CodeViewerProps) {
  return (
    <MonacoCodeViewer
      value={value}
      language={language}
      className={className}
      height={height}
      customThemeName="soopa-theme"
      beforeMount={(monaco) => registerEdiLanguageAndTheme(monaco)}
    />
  );
}
