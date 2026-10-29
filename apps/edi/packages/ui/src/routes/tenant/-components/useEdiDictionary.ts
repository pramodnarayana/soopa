import { ApiErrorCode, FetchHttpClientAdapter, StructuredJsonLoggerAdapter } from '@soopa/ui';
import { useEffect, useMemo, useState } from 'react';

export interface EdiDictionary {
  segments: Record<string, { info: string; elements: string[] }>;
  elements: Record<string, string>;
}

export interface EdiDocument {
  interchange_ISA?: { ISA?: { ISA12?: string } } | Array<{ ISA?: { ISA12?: string } }>;
  interchange_UNB?: unknown;
  [key: string]: unknown;
}

function resolvePrimaryDocument(data: EdiDocument | EdiDocument[]): EdiDocument | undefined {
  return Array.isArray(data) ? data[0] : data;
}

function extractX12Version(isaWrapper: NonNullable<EdiDocument['interchange_ISA']>): string {
  const isa = Array.isArray(isaWrapper) ? isaWrapper[0] : isaWrapper;
  const rawVersion = isa?.ISA?.ISA12?.trim() ?? '';
  return rawVersion.length === 5 ? `${rawVersion.substring(2)}0` : '5011';
}

function deriveStandardAndVersion(data: EdiDocument | EdiDocument[]): {
  readonly standard: string;
  readonly version: string;
} {
  const doc = resolvePrimaryDocument(data);
  if (doc?.interchange_ISA) {
    return { standard: 'x12', version: extractX12Version(doc.interchange_ISA) };
  }
  if (doc?.interchange_UNB) {
    return { standard: 'edifact', version: 'd96a' };
  }
  return { standard: 'x12', version: '5011' };
}

function mergeDictionaryOverride(
  base: EdiDictionary,
  override: Partial<EdiDictionary>,
): EdiDictionary {
  return {
    segments: { ...base.segments, ...(override.segments ?? {}) },
    elements: { ...base.elements, ...(override.elements ?? {}) },
  };
}

export function useEdiDictionary(data: EdiDocument | EdiDocument[]) {
  const [dictionary, setDictionary] = useState<EdiDictionary | null>(null);
  const [loading, setLoading] = useState(true);

  const { standard, version } = useMemo(() => deriveStandardAndVersion(data), [data]);

  useEffect(() => {
    const abortController = new AbortController();
    const logger = new StructuredJsonLoggerAdapter({
      bindings: { product: 'edi', component: 'useEdiDictionary', standard, version },
    });
    const client = new FetchHttpClientAdapter({
      baseUrl: '/edidescription',
      logger,
    });

    const loadDictionary = async (): Promise<void> => {
      setLoading(true);
      const baseRes = await client.get<EdiDictionary>(`/${standard}.json`, {
        signal: abortController.signal,
      });

      if (abortController.signal.aborted) {
        return;
      }

      if (!baseRes.ok) {
        logger.error('edi_dictionary.base_load_failed', {
          error_code: baseRes.error.code,
          status: baseRes.error.status,
        });
        setDictionary(null);
        setLoading(false);
        return;
      }

      if (standard === 'x12' && version === '5011') {
        setDictionary(baseRes.value);
        setLoading(false);
        return;
      }

      const overrideRes = await client.get<Partial<EdiDictionary>>(`/${standard}_${version}.json`, {
        signal: abortController.signal,
      });

      if (abortController.signal.aborted) {
        return;
      }

      if (overrideRes.ok) {
        setDictionary(mergeDictionaryOverride(baseRes.value, overrideRes.value));
      } else {
        if (overrideRes.error.code === ApiErrorCode.NOT_FOUND) {
          logger.info('edi_dictionary.override_missing_fallback_to_base');
        } else {
          logger.error('edi_dictionary.override_load_failed', {
            error_code: overrideRes.error.code,
            status: overrideRes.error.status,
          });
        }
        setDictionary(baseRes.value);
      }
      setLoading(false);
    };

    void loadDictionary();
    return () => {
      abortController.abort();
    };
  }, [standard, version]);

  return { dictionary, loading };
}
