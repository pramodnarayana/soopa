import { EdiEditorPane } from '@/components/ui/edi-editor-pane';

export interface CertificateInputProps {
  value: string;
  onChange: (pem: string) => void;
}

/**
 * Reusable certificate input powered by Monaco Editor.
 * Supports drag-and-drop, file picker, and pasting raw PEM text natively.
 */
export function CertificateInput({ value, onChange }: CertificateInputProps) {
  return (
    <div className="border border-slate-200 rounded-xl overflow-hidden h-[250px] flex flex-col">
      <EdiEditorPane
        value={value}
        onChange={onChange}
        language="plaintext"
        placeholder="or click anywhere to paste raw PEM"
        cornerPlaceholder={"-----BEGIN CERTIFICATE-----\nMIID...\n-----END CERTIFICATE-----"}
      />
    </div>
  );
}
