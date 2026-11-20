/**
 * Domain types for declarative Field Mapping Specs connecting canonical events to wire schemas.
 */

export const MappingSpecRuleType = {
  DIRECT: 'DIRECT',
  CONSTANT: 'CONSTANT',
  EXPRESSION: 'EXPRESSION',
  IGNORE: 'IGNORE',
} as const;

export type MappingSpecRuleTypeValue =
  (typeof MappingSpecRuleType)[keyof typeof MappingSpecRuleType];

export interface MappingSpecRule {
  readonly targetField: string;
  readonly ruleType: MappingSpecRuleTypeValue;
  readonly sourceField?: string | null;
  readonly constantValue?: string | number | boolean | null;
  readonly expression?: string | null;
}

export interface MappingSpec {
  readonly id: string;
  readonly tenantId: string;
  readonly name: string;
  readonly description: string;
  readonly sourceType: string;
  readonly targetConnectionId: string;
  readonly targetEntityName: string;
  readonly version: number;
  readonly rules: readonly MappingSpecRule[];
  readonly isActive: boolean;
}

export interface SaveMappingSpecInput {
  readonly mappingSpecId?: string | null;
  readonly name: string;
  readonly description?: string;
  readonly sourceType: string;
  readonly targetConnectionId: string;
  readonly targetEntityName: string;
  readonly rules: readonly MappingSpecRule[];
  readonly isActive?: boolean;
}

export interface ListMappingSpecsFilter {
  readonly sourceType?: string;
  readonly targetConnectionId?: string;
}
