import React from 'react';
import { EdiEditorPane } from '@/components/ui/edi-editor-pane';

export interface CertificateInputProps {
  value: string;
  onChange: (pem: string) => void;
  extraActions?: React.ReactNode;
}

/**
 * Reusable certificate input powered by Monaco Editor.
 * Supports drag-and-drop, file picker, and pasting raw PEM text natively.
 */
export function CertificateInput({ value, onChange, extraActions }: CertificateInputProps) {
  return (
    <div className="border border-slate-200 rounded-xl overflow-hidden h-[420px] flex flex-col">
      <EdiEditorPane
        value={value}
        onChange={onChange}
        language="plaintext"
        cornerPlaceholder={"-----BEGIN CERTIFICATE-----\n-----END CERTIFICATE-----"}
        showEmptyState={false}
        extraActions={extraActions}
        fontSize={14}
        showCertDetected
        acceptedFileExtensions=".pem,.crt,.cer,.cert,.key,.txt"
      />
    </div>
  );
}
