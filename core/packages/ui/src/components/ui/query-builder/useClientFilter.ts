import { useMemo, useState } from 'react';
import { FilterRule } from './types';

function getNestedValue(obj: any, path: string): any {
  return path
    .split('.')
    .reduce((acc, part) => (acc && acc[part] !== undefined ? acc[part] : undefined), obj);
}

export function applyFilters<T>(data: T[], filters: FilterRule[]): T[] {
  if (!data) return [];
  if (filters.length === 0) return data;

  return data.filter((item) => {
    return filters.every((rule) => {
      const rawValue = getNestedValue(item, rule.field);

      // Handle null checks first
      if (rule.operator === 'is_null') {
        return rawValue === null || rawValue === undefined || rawValue === '';
      }
      if (rule.operator === 'is_not_null') {
        return rawValue !== null && rawValue !== undefined && rawValue !== '';
      }

      const val = String(rawValue ?? '').toLowerCase();
      const ruleVal = String(rule.value ?? '').toLowerCase();

      switch (rule.operator) {
        case 'eq':
          return val === ruleVal;
        case 'neq':
          return val !== ruleVal;
        case 'contains':
          return val.includes(ruleVal);
        case 'not_contains':
          return !val.includes(ruleVal);
        case 'gt': {
          if (rawValue == null || rule.value == null) return false;
          const leftVal = isNaN(Number(rawValue))
            ? new Date(String(rawValue)).getTime()
            : Number(rawValue);
          const rightVal = isNaN(Number(rule.value))
            ? new Date(String(rule.value)).getTime()
            : Number(rule.value);
          return leftVal > rightVal;
        }
        case 'gte': {
          if (rawValue == null || rule.value == null) return false;
          const leftVal = isNaN(Number(rawValue))
            ? new Date(String(rawValue)).getTime()
            : Number(rawValue);
          const rightVal = isNaN(Number(rule.value))
            ? new Date(String(rule.value)).getTime()
            : Number(rule.value);
          return leftVal >= rightVal;
        }
        case 'lt': {
          if (rawValue == null || rule.value == null) return false;
          const leftVal = isNaN(Number(rawValue))
            ? new Date(String(rawValue)).getTime()
            : Number(rawValue);
          const rightVal = isNaN(Number(rule.value))
            ? new Date(String(rule.value)).getTime()
            : Number(rule.value);
          return leftVal < rightVal;
        }
        case 'lte': {
          if (rawValue == null || rule.value == null) return false;
          const leftVal = isNaN(Number(rawValue))
            ? new Date(String(rawValue)).getTime()
            : Number(rawValue);
          const rightVal = isNaN(Number(rule.value))
            ? new Date(String(rule.value)).getTime()
            : Number(rule.value);
          return leftVal <= rightVal;
        }
        case 'in': {
          // Assume rule.value is a comma-separated string if text, or array
          const inArr = Array.isArray(rule.value) ? rule.value : String(rule.value).split(',');
          return inArr.map((i) => String(i).trim().toLowerCase()).includes(val);
        }
        case 'not_in': {
          const notInArr = Array.isArray(rule.value) ? rule.value : String(rule.value).split(',');
          return !notInArr.map((i) => String(i).trim().toLowerCase()).includes(val);
        }
        default:
          return true;
      }
    });
  });
}

export function useClientFilter<T>(data: T[]) {
  const [filters, setFilters] = useState<FilterRule[]>([]);

  const filteredData = useMemo(() => applyFilters(data, filters), [data, filters]);

  return {
    filters,
    setFilters,
    filteredData,
  };
}
