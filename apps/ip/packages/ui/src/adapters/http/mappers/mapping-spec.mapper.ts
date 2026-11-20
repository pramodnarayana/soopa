import type {
  MappingSpec,
  MappingSpecRule,
  MappingSpecRuleTypeValue,
  SaveMappingSpecInput,
} from '../../../domain/mapping-spec';
import type { MappingRuleWire, MappingSpecWire } from '../schemas/mapping-spec.schema';

function normalizeRuleType(ruleType: string): MappingSpecRuleTypeValue {
  const upper = ruleType.toUpperCase();
  if (upper === 'CONSTANT') return 'CONSTANT';
  if (upper === 'EXPRESSION') return 'EXPRESSION';
  if (upper === 'IGNORE') return 'IGNORE';
  return 'DIRECT';
}

export function mapMappingRuleFromWire(wire: MappingRuleWire): MappingSpecRule {
  return {
    targetField: wire.target_field,
    ruleType: normalizeRuleType(wire.rule_type),
    sourceField: wire.source_field,
    constantValue: wire.constant_value,
    expression: wire.expression,
  };
}

export function mapMappingSpecFromWire(wire: MappingSpecWire): MappingSpec {
  return {
    id: wire.id,
    tenantId: wire.tenant_id,
    name: wire.name,
    description: wire.description ?? '',
    sourceType: wire.source_type,
    targetConnectionId: wire.target_connection_id,
    targetEntityName: wire.target_entity_name,
    version: wire.version,
    rules: wire.rules.map(mapMappingRuleFromWire),
    isActive: wire.is_active,
  };
}

export function mapSaveMappingSpecToWire(input: SaveMappingSpecInput): Record<string, unknown> {
  return {
    mapping_spec_id: input.mappingSpecId ?? null,
    name: input.name,
    description: input.description ?? '',
    source_type: input.sourceType,
    target_connection_id: input.targetConnectionId,
    target_entity_name: input.targetEntityName,
    rules: input.rules.map((r) => ({
      target_field: r.targetField,
      rule_type: r.ruleType,
      source_field: r.sourceField ?? null,
      constant_value: r.constantValue ?? null,
      expression: r.expression ?? null,
    })),
    is_active: input.isActive ?? true,
  };
}
