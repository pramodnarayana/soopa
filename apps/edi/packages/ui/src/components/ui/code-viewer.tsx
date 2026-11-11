import { MonacoCodeViewer } from '@soopa/ui';
import { useTheme } from 'next-themes';
import type { JSX } from 'react';
import { registerEdiLanguageAndTheme, resolveEdiMonacoTheme } from '../../utils/monaco-edi';

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
}: CodeViewerProps): JSX.Element {
  const { resolvedTheme } = useTheme();
  return (
    <MonacoCodeViewer
      value={value}
      language={language}
      className={className}
      height={height}
      customThemeName={resolveEdiMonacoTheme(resolvedTheme)}
      beforeMount={registerEdiLanguageAndTheme}
    />
  );
}
