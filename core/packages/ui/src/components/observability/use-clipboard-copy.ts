import { useCallback, useEffect, useRef, useState } from 'react';

export interface ClipboardWriterPort {
  writeText(text: string): Promise<void>;
}

/**
 * Safely writes text to a clipboard writer without throwing unhandled rejections
 * in restricted focus/iframe contexts (e.g. DOMException: NotAllowedError).
 */
export async function writeTextSafely(
  text: string,
  clipboard: ClipboardWriterPort | null | undefined,
): Promise<boolean> {
  if (!clipboard) {
    return false;
  }
  try {
    await clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function resolveBrowserClipboard(): ClipboardWriterPort | null {
  if (typeof navigator === 'undefined' || !navigator.clipboard) {
    return null;
  }
  return navigator.clipboard;
}

export function useClipboardCopy(
  resetMs = 1_600,
  clipboardOverride?: ClipboardWriterPort | null,
): {
  readonly copied: boolean;
  readonly copyText: (text: string) => Promise<boolean>;
} {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
    },
    [],
  );

  const copyText = useCallback(
    async (text: string): Promise<boolean> => {
      const target =
        clipboardOverride === undefined ? resolveBrowserClipboard() : clipboardOverride;
      const didCopy = await writeTextSafely(text, target);
      if (!didCopy) {
        setCopied(false);
        return false;
      }
      setCopied(true);
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
      timerRef.current = setTimeout(() => {
        setCopied(false);
      }, resetMs);
      return true;
    },
    [clipboardOverride, resetMs],
  );

  return { copied, copyText };
}
