import axios from 'axios';
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

export function useEdiDictionary(data: EdiDocument | EdiDocument[]) {
  const [dictionary, setDictionary] = useState<EdiDictionary | null>(null);
  const [loading, setLoading] = useState(true);

  // 1. Determine standard and version
  const { standard, version } = useMemo(() => {
    let standard = 'x12';
    let version = '5011';

    if (!Array.isArray(data) && data?.interchange_ISA) {
      standard = 'x12';
      const isaWrapper = data.interchange_ISA;
      const isa = Array.isArray(isaWrapper) ? isaWrapper[0] : isaWrapper;
      if (isa?.ISA?.ISA12) {
        const v = isa.ISA.ISA12.trim();
        if (v.length === 5) {
          version = v.substring(2) + '0'; // e.g. 00401 -> 4010
        }
      }
    } else if (Array.isArray(data) && data[0]?.interchange_ISA) {
      standard = 'x12';
      const isaWrapper = data[0].interchange_ISA;
      const isa = Array.isArray(isaWrapper) ? isaWrapper[0] : isaWrapper;
      if (isa?.ISA?.ISA12) {
        const v = isa.ISA.ISA12.trim();
        if (v.length === 5) {
          version = v.substring(2) + '0'; // e.g. 00401 -> 4010
        }
      }
    } else if (!Array.isArray(data) && data?.interchange_UNB) {
      standard = 'edifact';
      version = 'd96a'; // default edifact version
    } else if (Array.isArray(data) && data[0]?.interchange_UNB) {
      standard = 'edifact';
      version = 'd96a'; // default edifact version
    }

    return { standard, version };
  }, [data]);

  useEffect(() => {
    let isCancelled = false;

    const fetchDictionary = async () => {
      setLoading(true);

      try {
        // 2. Fetch base dictionary
        const baseRes = await axios.get<EdiDictionary>(`/edidescription/${standard}.json`);
        if (isCancelled) return;

        let finalDict = baseRes.data;

        // 3. Try fetching version-specific override
        // Update: use the existing x12.json by key unless distinct X12 5011 release data is available
        if (standard === 'x12' && version === '5011') {
          if (!isCancelled) {
            setDictionary(finalDict);
            setLoading(false);
          }
          return;
        }

        try {
          const overrideRes = await axios.get<Partial<EdiDictionary>>(
            `/edidescription/${standard}_${version}.json`,
          );
          if (isCancelled) return;
          // Deep merge the overrides
          finalDict = {
            segments: { ...finalDict.segments, ...(overrideRes.data.segments || {}) },
            elements: { ...finalDict.elements, ...(overrideRes.data.elements || {}) },
          };
        } catch (err: unknown) {
          if (axios.isAxiosError(err) && err.response?.status === 404) {
            console.log(
              `No version override found for ${standard}_${version}.json, using base dictionary.`,
            );
          } else {
            console.warn(`Failed to fetch version override for ${standard}_${version}.json:`, err);
          }
        }

        if (!isCancelled) {
          setDictionary(finalDict);
          setLoading(false);
        }
      } catch (err) {
        console.error(`Failed to load base dictionary for ${standard}`, err);
        if (!isCancelled) {
          setDictionary(null);
          setLoading(false);
        }
      }
    };

    void fetchDictionary();

    return () => {
      isCancelled = true;
    };
  }, [standard, version]);

  return { dictionary, loading };
}
