import { useState, useEffect, useMemo } from 'react';
import axios from 'axios';

export interface EdiDictionary {
  segments: Record<string, { info: string; elements: string[] }>;
  elements: Record<string, string>;
}

export function useEdiDictionary(data: any) {
  const [dictionary, setDictionary] = useState<EdiDictionary | null>(null);
  const [loading, setLoading] = useState(true);

  // 1. Determine standard and version
  const { standard, version } = useMemo(() => {
    let standard = 'x12';
    let version = '5011';

    if (data?.interchange_ISA || (Array.isArray(data) && data[0]?.interchange_ISA)) {
      standard = 'x12';
      const isaWrapper = Array.isArray(data) ? data[0].interchange_ISA : data.interchange_ISA;
      const isa = Array.isArray(isaWrapper) ? isaWrapper[0] : isaWrapper;
      if (isa?.ISA?.ISA12) {
        const v = isa.ISA.ISA12.trim();
        if (v.length === 5) {
          version = v.substring(2) + '0'; // e.g. 00401 -> 4010
        }
      }
    } else if (data?.interchange_UNB || (Array.isArray(data) && data[0]?.interchange_UNB)) {
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
        const baseRes = await axios.get(`/edidescription/${standard}.json`);
        if (isCancelled) return;

        let finalDict = baseRes.data;

        // 3. Try fetching version-specific override
        try {
          const overrideRes = await axios.get(`/edidescription/${standard}_${version}.json`);
          if (isCancelled) return;
          // Deep merge the overrides
          finalDict = {
            segments: { ...finalDict.segments, ...(overrideRes.data.segments || {}) },
            elements: { ...finalDict.elements, ...(overrideRes.data.elements || {}) }
          };
        } catch {
          // Version-specific override is optional, so we ignore 404s
          console.log(`No version override found for ${standard}_${version}.json, using base dictionary.`);
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

    fetchDictionary();

    return () => {
      isCancelled = true;
    };
  }, [standard, version]);

  return { dictionary, loading };
}
