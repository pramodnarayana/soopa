import type { MonacoInstance } from '@soopa/ui';

export const EdiMonacoTheme = {
  LIGHT: 'soopa-edi-light',
  DARK: 'soopa-edi-dark',
} as const;

export type EdiMonacoThemeValue = (typeof EdiMonacoTheme)[keyof typeof EdiMonacoTheme];

export function resolveEdiMonacoTheme(resolvedTheme: string | undefined): EdiMonacoThemeValue {
  return resolvedTheme === 'dark' ? EdiMonacoTheme.DARK : EdiMonacoTheme.LIGHT;
}

export function registerEdiLanguageAndTheme(monacoInstance: MonacoInstance): void {
  if (!monacoInstance.languages.getLanguages().some((lang) => lang.id === 'edi')) {
    monacoInstance.languages.register({ id: 'edi' });
    monacoInstance.languages.setMonarchTokensProvider('edi', {
      tokenizer: {
        root: [
          [/^[A-Z0-9]{2,3}(?=\*)/, 'keyword'],
          [/(~\s*)([A-Z0-9]{2,3})(?=\*)/, ['delimiter', 'keyword']],
          [/\*/, 'delimiter'],
          [/~/, 'delimiter'],
          [/[^*~\n\r]+/, 'string'],
        ],
      },
    });
  }

  monacoInstance.editor.defineTheme(EdiMonacoTheme.LIGHT, {
    base: 'vs',
    inherit: true,
    rules: [
      { token: 'keyword', foreground: '0451a5', fontStyle: 'bold' },
      { token: 'string', foreground: '065f46' },
      { token: 'delimiter', foreground: '0f172a' },
      { token: 'string.key.json', foreground: '0451a5', fontStyle: 'bold' },
      { token: 'string.value.json', foreground: '065f46' },
      { token: 'number.json', foreground: '065f46' },
      { token: 'keyword.json', foreground: '0451a5', fontStyle: 'bold' },
    ],
    colors: {},
  });

  monacoInstance.editor.defineTheme(EdiMonacoTheme.DARK, {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'keyword', foreground: '60a5fa', fontStyle: 'bold' },
      { token: 'string', foreground: '34d399' },
      { token: 'delimiter', foreground: 'e2e8f0' },
      { token: 'string.key.json', foreground: '60a5fa', fontStyle: 'bold' },
      { token: 'string.value.json', foreground: '34d399' },
      { token: 'number.json', foreground: '34d399' },
      { token: 'keyword.json', foreground: '60a5fa', fontStyle: 'bold' },
    ],
    colors: {},
  });
}
