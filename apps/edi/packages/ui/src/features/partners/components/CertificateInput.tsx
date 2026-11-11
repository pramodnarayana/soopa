import { Check } from 'lucide-react';
import type { JSX, ReactNode } from 'react';
import { EdiEditorPane } from '../../../components/ui/edi-editor-pane';

export interface CertificateInputProps {
  readonly value: string;
  readonly onChange: (pem: string) => void;
  readonly extraActions?: ReactNode;
}

function renderPemDetectedBanner(currentValue: string): ReactNode {
  if (
    !currentValue ||
    !currentValue.includes('-----BEGIN CERTIFICATE-----') ||
    !currentValue.includes('-----END CERTIFICATE-----')
  ) {
    return null;
  }

  return (
    <div className="pointer-events-none flex items-center gap-2 border-t border-emerald-200 bg-emerald-50 px-4 py-2 text-xs font-semibold text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
      <Check className="h-3.5 w-3.5 shrink-0" />
      <span>Certificate detected — ready to save</span>
    </div>
  );
}

/**
 * Reusable certificate input powered by MonacoCodeEditor via EdiEditorPane.
 * Supports drag-and-drop, file picker, and pasting raw PEM text natively.
 */
export function CertificateInput({
  value,
  onChange,
  extraActions,
}: CertificateInputProps): JSX.Element {
  return (
    <div className="flex h-[440px] flex-col overflow-hidden rounded-xl border border-border">
      <EdiEditorPane
        value={value}
        onChange={onChange}
        language="plaintext"
        cornerPlaceholder={'-----BEGIN CERTIFICATE-----\n-----END CERTIFICATE-----'}
        emptyPrompt={null}
        extraActions={extraActions}
        fontSize={14}
        renderStatusBanner={renderPemDetectedBanner}
        acceptedFileExtensions=".pem,.crt,.cer,.cert,.key,.txt"
      />
    </div>
  );
}
