/**
 * Domain types and pure logic for visual field alignment, schema inference,
 * and outbound wire projections for the Route/Stitch Workbench.
 */

import { isPlainJsonRecord } from './replay/parse-json-object';

export interface TargetSchemaField {
  readonly name: string;
  readonly type: 'string' | 'number' | 'boolean' | 'object' | 'array';
  readonly required: boolean;
  readonly description?: string;
}

export const MappingRuleType = {
  DIRECT: 'DIRECT',
  FUNCTION: 'FUNCTION',
  CONSTANT: 'CONSTANT',
  IGNORE: 'IGNORE',
} as const;

export type MappingRuleTypeValue = (typeof MappingRuleType)[keyof typeof MappingRuleType];

export interface FieldMappingRule {
  readonly targetField: string;
  readonly ruleType: MappingRuleTypeValue;
  readonly sourceField?: string;
  readonly functionExpression?: string;
  readonly constantValue?: string | number | boolean;
}

export interface CanonicalFieldDef {
  readonly name: string;
  readonly type: 'string' | 'number' | 'boolean' | 'object' | 'array';
  readonly required: boolean;
  readonly description: string;
  readonly sampleValue: unknown;
}

export interface CanonicalModelDef {
  readonly transformationId: string;
  readonly version: number;
  readonly displayName: string;
  readonly canonicalEventType: string;
  readonly standard: string;
  readonly targetWorkflowId: string;
  readonly idempotencyKeyField: string;
  readonly concurrencyKeyField?: string;
  readonly fields: readonly CanonicalFieldDef[];
  readonly defaultSampleRecord: Record<string, unknown>;
}

/**
 * Pure function to infer TargetSchemaField[] from either a JSON Schema or a sample JSON payload.
 */
export function inferSchemaFromSampleJson(raw: string): {
  readonly fields: readonly TargetSchemaField[];
  readonly error: string | null;
} {
  const trimmed = raw.trim();
  if (!trimmed) {
    return { fields: [], error: 'Empty schema or payload provided.' };
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch (err: unknown) {
    return {
      fields: [],
      error: `Invalid JSON syntax: ${err instanceof Error ? err.message : 'Invalid JSON'}`,
    };
  }

  let obj: Record<string, unknown> | null = null;
  if (isPlainJsonRecord(parsed)) {
    obj = parsed;
  } else if (Array.isArray(parsed) && parsed.length > 0 && isPlainJsonRecord(parsed[0])) {
    obj = parsed[0];
  }

  if (!obj) {
    return { fields: [], error: 'Payload must be a JSON object or an array of objects.' };
  }

  // 1. Check if it's a JSON Schema definition (has `properties` object)
  if (obj.properties && typeof obj.properties === 'object' && !Array.isArray(obj.properties)) {
    const properties = obj.properties as Record<string, unknown>;
    const requiredList = Array.isArray(obj.required) ? (obj.required as string[]) : [];
    const fields: TargetSchemaField[] = [];

    for (const [propName, propDef] of Object.entries(properties)) {
      if (propDef && typeof propDef === 'object') {
        const pRecord = propDef as Record<string, unknown>;
        const rawType = String(pRecord.type ?? 'string');
        const validTypes: TargetSchemaField['type'][] = [
          'string',
          'number',
          'boolean',
          'object',
          'array',
        ];
        const normalizedType: TargetSchemaField['type'] = validTypes.includes(
          rawType as TargetSchemaField['type'],
        )
          ? (rawType as TargetSchemaField['type'])
          : 'string';

        fields.push({
          name: propName,
          type: normalizedType,
          required: requiredList.includes(propName),
          description: typeof pRecord.description === 'string' ? pRecord.description : undefined,
        });
      }
    }

    return { fields, error: null };
  }

  // 2. Otherwise treat as a concrete sample JSON payload
  const fields: TargetSchemaField[] = [];
  for (const [key, value] of Object.entries(obj)) {
    let fieldType: TargetSchemaField['type'] = 'string';
    if (typeof value === 'number') {
      fieldType = 'number';
    } else if (typeof value === 'boolean') {
      fieldType = 'boolean';
    } else if (Array.isArray(value)) {
      fieldType = 'array';
    } else if (value !== null && typeof value === 'object') {
      fieldType = 'object';
    }

    fields.push({
      name: key,
      type: fieldType,
      required: true,
      description: `Inferred from sample payload (${fieldType})`,
    });
  }

  return { fields, error: null };
}

function normalizeFieldName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, '');
}

/**
 * Pure auto-mapping function that maps source canonical fields to target wire schema fields
 * using exact matching, case-insensitive normalized matching, and prefix/suffix matching.
 */
export function autoMapFields(
  sourceFields: readonly string[],
  targetFields: readonly TargetSchemaField[],
): FieldMappingRule[] {
  const normSourceMap = new Map<string, string>();
  for (const src of sourceFields) {
    normSourceMap.set(normalizeFieldName(src), src);
  }

  return targetFields.map((target) => {
    // 1. Direct exact match
    if (sourceFields.includes(target.name)) {
      return {
        targetField: target.name,
        ruleType: MappingRuleType.DIRECT,
        sourceField: target.name,
      };
    }

    // 2. Normalized alphanumeric match (case-insensitive, ignoring _, -, camelCase)
    const targetNorm = normalizeFieldName(target.name);
    const directNormMatch = normSourceMap.get(targetNorm);
    if (directNormMatch) {
      return {
        targetField: target.name,
        ruleType: MappingRuleType.DIRECT,
        sourceField: directNormMatch,
      };
    }

    // 3. Substring / suffix boundary match
    const boundaryMatch = sourceFields.find((src) => {
      const srcNorm = normalizeFieldName(src);
      return (
        (srcNorm.length >= 3 && targetNorm.endsWith(srcNorm)) ||
        (targetNorm.length >= 3 && srcNorm.endsWith(targetNorm))
      );
    });
    if (boundaryMatch) {
      return {
        targetField: target.name,
        ruleType: MappingRuleType.DIRECT,
        sourceField: boundaryMatch,
      };
    }

    // 4. Default: IGNORE
    return {
      targetField: target.name,
      ruleType: MappingRuleType.IGNORE,
    };
  });
}

/**
 * Pure evaluation function that executes the field mapping rules against an L3 Canonical source record
 * to produce the projected target wire payload.
 */
export function applyFieldMappings(
  sourcePayload: Record<string, unknown>,
  rules: readonly FieldMappingRule[],
): Record<string, unknown> {
  const output: Record<string, unknown> = {};

  for (const rule of rules) {
    if (rule.ruleType === MappingRuleType.IGNORE) {
      continue;
    }

    if (rule.ruleType === MappingRuleType.DIRECT && rule.sourceField) {
      output[rule.targetField] = sourcePayload[rule.sourceField] ?? null;
      continue;
    }

    if (rule.ruleType === MappingRuleType.CONSTANT) {
      output[rule.targetField] = rule.constantValue ?? null;
      continue;
    }

    if (rule.ruleType === MappingRuleType.FUNCTION) {
      const expr = (rule.functionExpression ?? '').trim();
      const val = rule.sourceField ? sourcePayload[rule.sourceField] : undefined;

      if (expr.startsWith('UPPER(') && val !== undefined) {
        output[rule.targetField] = String(val).toUpperCase();
      } else if (expr.startsWith('LOWER(') && val !== undefined) {
        output[rule.targetField] = String(val).toLowerCase();
      } else if (expr.startsWith('ROUND(') && typeof val === 'number') {
        output[rule.targetField] = Math.round(val * 100) / 100;
      } else if (expr.startsWith('STRING(') && val !== undefined) {
        output[rule.targetField] = String(val);
      } else if (expr.startsWith('NUMBER(') && val !== undefined) {
        output[rule.targetField] = Number(val);
      } else {
        // Fallback pass-through if function syntax is basic or unrecognized
        output[rule.targetField] = val ?? null;
      }
    }
  }

  return output;
}
