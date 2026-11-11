import { cn, MonacoCodeEditor, MonacoFileToolbarVisibility } from '@soopa/ui';
import { useTheme } from 'next-themes';
import type { JSX, ReactNode } from 'react';
import { registerEdiLanguageAndTheme, resolveEdiMonacoTheme } from '../../utils/monaco-edi';

export interface EdiEditorPaneProps {
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly language?: 'edi' | 'json' | 'plaintext';
  readonly emptyPrompt?: string | null;
  readonly cornerPlaceholder?: string;
  readonly className?: string;
  readonly acceptedFileExtensions?: string;
  readonly extraActions?: ReactNode;
  readonly fontSize?: number;
  readonly renderStatusBanner?: (currentValue: string) => ReactNode;
}

export function EdiEditorPane({
  value,
  onChange,
  language = 'edi',
  emptyPrompt,
  cornerPlaceholder,
  className = '',
  acceptedFileExtensions = '.edi,.json,.txt,.x12',
  extraActions,
  fontSize = 13,
  renderStatusBanner,
}: EdiEditorPaneProps): JSX.Element {
  const { resolvedTheme } = useTheme();
  const resolvedEmptyPrompt =
    emptyPrompt === undefined ? `Drag & drop or paste ${language.toUpperCase()}` : emptyPrompt;

  return (
    <MonacoCodeEditor
      value={value}
      onChange={onChange}
      language={language}
      height="100%"
      fontSize={fontSize}
      customThemeName={resolveEdiMonacoTheme(resolvedTheme)}
      cornerPlaceholder={cornerPlaceholder}
      statusBanner={renderStatusBanner ? renderStatusBanner(value) : null}
      beforeMount={registerEdiLanguageAndTheme}
      className={cn('min-h-[250px] flex-1 rounded-none border-0', className)}
      fileUpload={{
        accept: acceptedFileExtensions,
        maxBytes: 1_048_576,
        emptyPrompt: resolvedEmptyPrompt,
        toolbarVisibility: MonacoFileToolbarVisibility.EMPTY_ONLY,
        extraActions,
      }}
    />
  );
}
