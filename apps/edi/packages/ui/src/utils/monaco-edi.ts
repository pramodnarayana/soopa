export function registerEdiLanguageAndTheme(monaco: any) {
  if (!monaco.languages.getLanguages().some((l: any) => l.id === 'edi')) {
    monaco.languages.register({ id: 'edi' });
    monaco.languages.setMonarchTokensProvider('edi', {
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
  monaco.editor.defineTheme('soopa-theme', {
    base: 'vs',
    inherit: true,
    rules: [
      { token: 'keyword', foreground: '0451a5', fontStyle: 'bold' },
      { token: 'string', foreground: '065f46' },
      { token: 'delimiter', foreground: '000000' },
      { token: 'string.key.json', foreground: '0451a5', fontStyle: 'bold' },
      { token: 'string.value.json', foreground: '065f46' },
      { token: 'number.json', foreground: '065f46' },
      { token: 'keyword.json', foreground: '0451a5', fontStyle: 'bold' },
    ],
    colors: {
      'editor.background': '#ffffff',
    }
  });
}
