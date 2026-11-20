import { describe, expect, it } from 'vitest';
import {
  applyFieldMappings,
  autoMapFields,
  inferSchemaFromSampleJson,
  MappingRuleType,
  type TargetSchemaField,
} from '../domain/field-mapping';

describe('field-mapping domain logic', () => {
  it('infers schema from a sample JSON payload', () => {
    const sample = JSON.stringify({
      recordId: 'REC-1001',
      recordedAt: '2026-11-15T00:00:00Z',
      numericValue: 142.85,
      isActive: true,
    });

    const result = inferSchemaFromSampleJson(sample);
    expect(result.error).toBeNull();
    expect(result.fields).toHaveLength(4);
    expect(result.fields[0]).toEqual({
      name: 'recordId',
      type: 'string',
      required: true,
      description: 'Inferred from sample payload (string)',
    });
    expect(result.fields[2]).toEqual({
      name: 'numericValue',
      type: 'number',
      required: true,
      description: 'Inferred from sample payload (number)',
    });
  });

  it('infers schema from a JSON Schema definition with properties plus required array', () => {
    const jsonSchema = JSON.stringify({
      type: 'object',
      required: ['recordId', 'recordedAt'],
      properties: {
        recordId: { type: 'string', description: 'Unique Record Identifier' },
        recordedAt: { type: 'string' },
        statusCode: { type: 'string' },
      },
    });

    const result = inferSchemaFromSampleJson(jsonSchema);
    expect(result.error).toBeNull();
    expect(result.fields).toHaveLength(3);
    const idField = result.fields.find((f) => f.name === 'recordId');
    expect(idField?.required).toBe(true);
    expect(idField?.description).toBe('Unique Record Identifier');
    const statusField = result.fields.find((f) => f.name === 'statusCode');
    expect(statusField?.required).toBe(false);
  });

  it('returns clean error when given invalid JSON', () => {
    const result = inferSchemaFromSampleJson('{ invalid json');
    expect(result.error).toContain('Invalid JSON syntax');
    expect(result.fields).toHaveLength(0);
  });

  it('auto-maps canonical fields to wire fields using normalized algorithmic matching', () => {
    const sourceFields = [
      'record_id',
      'created_at',
      'payload_value',
      'status_flag',
      'partner_code',
    ];

    const targetFields: TargetSchemaField[] = [
      { name: 'recordId', type: 'string', required: true },
      { name: 'createdAt', type: 'string', required: true },
      { name: 'payloadValue', type: 'number', required: true },
      { name: 'statusFlag', type: 'string', required: false },
      { name: 'unmatchedTarget', type: 'string', required: false },
    ];

    const rules = autoMapFields(sourceFields, targetFields);
    expect(rules).toHaveLength(targetFields.length);

    const idRule = rules.find((r) => r.targetField === 'recordId');
    expect(idRule?.ruleType).toBe(MappingRuleType.DIRECT);
    expect(idRule?.sourceField).toBe('record_id');

    const timeRule = rules.find((r) => r.targetField === 'createdAt');
    expect(timeRule?.ruleType).toBe(MappingRuleType.DIRECT);
    expect(timeRule?.sourceField).toBe('created_at');

    const valRule = rules.find((r) => r.targetField === 'payloadValue');
    expect(valRule?.ruleType).toBe(MappingRuleType.DIRECT);
    expect(valRule?.sourceField).toBe('payload_value');

    const statusRule = rules.find((r) => r.targetField === 'statusFlag');
    expect(statusRule?.ruleType).toBe(MappingRuleType.DIRECT);
    expect(statusRule?.sourceField).toBe('status_flag');

    const unmatchedRule = rules.find((r) => r.targetField === 'unmatchedTarget');
    expect(unmatchedRule?.ruleType).toBe(MappingRuleType.IGNORE);
  });

  it('applies field mapping rules to transform a canonical record into the wire payload', () => {
    const sampleRecord = {
      record_id: 'REC-7721',
      created_at: '2026-11-15T12:00:00Z',
      metric_value: 55.4321,
      status_flag: 'validated',
    };

    const rules = [
      {
        targetField: 'recordId',
        ruleType: MappingRuleType.DIRECT,
        sourceField: 'record_id',
      },
      {
        targetField: 'createdAt',
        ruleType: MappingRuleType.DIRECT,
        sourceField: 'created_at',
      },
      {
        targetField: 'metricValue',
        ruleType: MappingRuleType.FUNCTION,
        sourceField: 'metric_value',
        functionExpression: 'ROUND(metric_value, 2)',
      },
      {
        targetField: 'statusFlag',
        ruleType: MappingRuleType.FUNCTION,
        sourceField: 'status_flag',
        functionExpression: 'UPPER(status_flag)',
      },
      {
        targetField: 'originTag',
        ruleType: MappingRuleType.CONSTANT,
        constantValue: 'PLATFORM_INGRESS',
      },
      {
        targetField: 'ignoredField',
        ruleType: MappingRuleType.IGNORE,
      },
    ];

    const output = applyFieldMappings(sampleRecord, rules);
    expect(output).toEqual({
      recordId: 'REC-7721',
      createdAt: '2026-11-15T12:00:00Z',
      metricValue: 55.43,
      statusFlag: 'VALIDATED',
      originTag: 'PLATFORM_INGRESS',
    });
    expect(output).not.toHaveProperty('ignoredField');
  });
});
